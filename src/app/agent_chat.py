"""Chat-facing router and three-layer memory for the local workbench.

The memory in this module is deliberately bounded and evidence-safe: it may
guide routing, style, and retrieval terms, but it never becomes report evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from src.models.model_adapter import ModelAdapter
from src.app.chat_task_parser import latest_completed_period, parse_chat_task
from src.retrieval.chroma_index import cosine_similarity, embed_texts
from src.utils.config import load_config


DEFAULT_MEMORY_BOUNDARY = "Memory is context only and never substitutes for evidence_id citations or verifier gates."


@dataclass
class ChatTurn:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content, "created_at": self.created_at}


class ShortTermChatMemory:
    """In-process sliding-window memory for a single chat session."""

    def __init__(self, max_turns: int = 10):
        self.max_turns = max(2, int(max_turns))
        self.turns: List[ChatTurn] = []
        self.pinned_facts: List[str] = []
        self.verifier_feedback: List[str] = []

    def add(self, role: str, content: str) -> None:
        text = _clean(content, limit=1400)
        if not text:
            return
        self.turns.append(ChatTurn(role=str(role), content=text))
        self.turns = self.turns[-self.max_turns :]

    def context_lines(self, max_chars: int = 1600) -> str:
        lines = ["[ShortTermMemory]", DEFAULT_MEMORY_BOUNDARY]
        if self.pinned_facts:
            lines.append("Pinned facts:")
            lines.extend(f"- {_clean(item, 180)}" for item in self.pinned_facts[-6:])
        if self.verifier_feedback:
            lines.append("Recent verifier feedback:")
            lines.extend(f"- {_clean(item, 180)}" for item in self.verifier_feedback[-4:])
        if self.turns:
            lines.append("Recent turns:")
            for turn in self.turns[-self.max_turns :]:
                lines.append(f"- {turn.role}: {_clean(turn.content, 220)}")
        return _truncate("\n".join(lines), max_chars)


class UserPreferenceMemory:
    """Schema-light user profile memory with rule-first extraction."""

    def __init__(self, root: str | Path = "memory/chat"):
        self.root = Path(root)

    def load(self, user_id: str) -> Dict[str, Any]:
        payload = _read_json(self._path(user_id))
        if not isinstance(payload.get("preferences"), dict):
            payload["preferences"] = {}
        payload.setdefault("user_id", user_id)
        payload.setdefault("updated_at", "")
        return payload

    def extract_and_save(self, user_id: str, text: str) -> List[Dict[str, Any]]:
        extracted = _extract_preferences(text)
        if not extracted:
            return []
        payload = self.load(user_id)
        preferences = payload.setdefault("preferences", {})
        changed: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc).isoformat()
        for item in extracted:
            key = item["key"]
            prior = preferences.get(key, {}) if isinstance(preferences.get(key), dict) else {}
            if _should_replace_preference(prior, item):
                row = {
                    "value": item["value"],
                    "confidence": item["confidence"],
                    "source": item["source"],
                    "updated_at": now,
                }
                preferences[key] = row
                changed.append({"key": key, **row})
        payload["updated_at"] = now
        _write_json(self._path(user_id), payload)
        return changed

    def render_context(self, user_id: str, max_chars: int = 900) -> str:
        payload = self.load(user_id)
        preferences = payload.get("preferences", {})
        if not isinstance(preferences, dict) or not preferences:
            return ""
        lines = ["[UserPreferences]", DEFAULT_MEMORY_BOUNDARY]
        for key in sorted(preferences):
            row = preferences[key]
            if isinstance(row, dict):
                lines.append(f"- {key}: {_clean(str(row.get('value', '')), 160)}")
        return _truncate("\n".join(lines), max_chars)

    def _path(self, user_id: str) -> Path:
        return self.root / "users" / f"{_safe_key(user_id)}.json"


class LongTermChatMemory:
    """Persistent semantic memory with vector-first and TF fallback scoring."""

    def __init__(self, root: str | Path = "memory/chat", max_items: int = 240):
        self.root = Path(root)
        self.max_items = int(max_items)

    def add(
        self,
        user_id: str,
        content: str,
        session_id: str,
        symbol: str = "",
        period: str = "",
        importance: float = 0.5,
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any] | None:
        text = _clean(content, limit=1200)
        if not text:
            return None
        items = self._load_items(user_id)
        vector = embed_texts([text])[0]
        for item in items:
            existing_vector = item.get("embedding")
            if isinstance(existing_vector, list) and cosine_similarity(vector, existing_vector) >= 0.96:
                item["importance"] = max(float(item.get("importance", 0.0) or 0.0), float(importance))
                item["last_accessed"] = datetime.now(timezone.utc).isoformat()
                self._save_items(user_id, items)
                return item
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "id": hashlib.sha1(f"{user_id}|{session_id}|{text}|{now}".encode("utf-8")).hexdigest()[:16],
            "content": text,
            "embedding": vector,
            "symbol": str(symbol or "").upper(),
            "period": str(period or ""),
            "session_id": session_id,
            "importance": float(importance),
            "created_at": now,
            "last_accessed": now,
            "metadata": dict(metadata or {}),
        }
        items.append(row)
        self._save_items(user_id, self._consolidate(items))
        return row

    def recall(
        self,
        user_id: str,
        query: str,
        symbol: str = "",
        period: str = "",
        topk: int = 4,
    ) -> List[Dict[str, Any]]:
        items = self._load_items(user_id)
        if not items:
            return []
        query_vector = embed_texts([query])[0]
        symbol_key = str(symbol or "").upper()
        period_key = str(period or "")
        scored: List[Dict[str, Any]] = []
        for item in items:
            if symbol_key and item.get("symbol") and item.get("symbol") != symbol_key:
                continue
            if period_key and item.get("period") and item.get("period") != period_key:
                continue
            vector_score = 0.0
            vector = item.get("embedding")
            if isinstance(vector, list):
                vector_score = max(0.0, cosine_similarity(query_vector, vector))
            tf_score = _tf_overlap(query, str(item.get("content", "")))
            recency = _recency_score(str(item.get("last_accessed") or item.get("created_at") or ""))
            importance = float(item.get("importance", 0.0) or 0.0)
            entity_boost = 0.08 if symbol_key and item.get("symbol") == symbol_key else 0.0
            score = 0.48 * vector_score + 0.24 * tf_score + 0.16 * importance + 0.12 * recency + entity_boost
            if score <= 0.08:
                continue
            row = {key: value for key, value in item.items() if key != "embedding"}
            row["score"] = round(score, 4)
            row["vector_score"] = round(vector_score, 4)
            row["tf_score"] = round(tf_score, 4)
            scored.append(row)
        scored.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        selected = scored[: max(0, int(topk))]
        if selected:
            touched = {item["id"] for item in selected}
            now = datetime.now(timezone.utc).isoformat()
            for item in items:
                if item.get("id") in touched:
                    item["last_accessed"] = now
            self._save_items(user_id, items)
        return selected

    def render_context(self, memories: List[Dict[str, Any]], max_chars: int = 1000) -> str:
        if not memories:
            return ""
        lines = ["[LongTermMemory]", DEFAULT_MEMORY_BOUNDARY]
        for item in memories:
            scope = " ".join(part for part in [str(item.get("symbol", "")), str(item.get("period", ""))] if part)
            prefix = f"{scope}: " if scope else ""
            lines.append(f"- {prefix}{_clean(str(item.get('content', '')), 220)}")
        return _truncate("\n".join(lines), max_chars)

    def _load_items(self, user_id: str) -> List[Dict[str, Any]]:
        payload = _read_json(self._path(user_id))
        items = payload.get("items", []) if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def _save_items(self, user_id: str, items: List[Dict[str, Any]]) -> None:
        payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat(), "items": items[-self.max_items :]}
        _write_json(self._path(user_id), payload)

    def _consolidate(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        for item in items:
            vector = item.get("embedding")
            merged = False
            for existing in deduped:
                existing_vector = existing.get("embedding")
                if isinstance(vector, list) and isinstance(existing_vector, list) and cosine_similarity(vector, existing_vector) >= 0.95:
                    if float(item.get("importance", 0.0) or 0.0) > float(existing.get("importance", 0.0) or 0.0):
                        existing.update(item)
                    merged = True
                    break
            if not merged:
                deduped.append(item)
        deduped.sort(key=lambda row: (float(row.get("importance", 0.0) or 0.0), str(row.get("last_accessed", ""))))
        return deduped[-self.max_items :]

    def _path(self, user_id: str) -> Path:
        return self.root / "long_term" / f"{_safe_key(user_id)}.json"


class AgentChatService:
    """Small chat router used by the local HTTP UI."""

    def __init__(
        self,
        config_path: str = "configs/model_backends.yaml",
        memory_root: str | Path = "memory/chat",
        output_root: str | Path = "data/outputs/multi_agent",
        report_root: str | Path = "data/reports/multi_agent",
    ):
        self.config_path = config_path
        self.output_root = Path(output_root)
        self.report_root = Path(report_root)
        self.short_term: Dict[str, ShortTermChatMemory] = {}
        self.long_term = LongTermChatMemory(memory_root)
        self.preferences = UserPreferenceMemory(memory_root)
        try:
            profile = _resolve_chat_profile(config_path)
            self.model = ModelAdapter.from_profile(profile=profile, config_path=config_path, fallback_section="agent_model")
        except Exception:
            self.model = ModelAdapter.from_config(config_path=config_path)

    def handle_chat(
        self,
        message: str,
        session_id: str = "default",
        user_id: str = "local_user",
        symbol: str = "",
        period: str = "",
        memory_enabled: bool = False,
        allow_report_run: bool = False,
        orchestrator: Any | None = None,
        engines: List[str] | None = None,
        fast: bool = True,
        execution_mode: str = "collaborative",
        enable_remote_data: bool = False,
        data_source_config_path: str = "configs/data_sources.yaml",
    ) -> Dict[str, Any]:
        text = _clean(message, limit=2000)
        if not text:
            return {"answer": "请输入要讨论的问题。", "mode": "chat", "memory_used": {}, "tool_trace": []}

        stm = self.short_term.setdefault(session_id, ShortTermChatMemory())
        stm.add("user", text)
        changed_preferences = self.preferences.extract_and_save(user_id, text) if memory_enabled else []
        recalled = self.long_term.recall(user_id=user_id, query=text, symbol=symbol, period=period) if memory_enabled else []
        route = self._route(text=text, allow_report_run=allow_report_run)
        if _looks_like_quality_review_text(text):
            route = {"mode": "quality_review", "reason": "review existing report quality artifacts"}
        trace = [
            {"stage": "think", "detail": f"route={route['mode']} reason={route['reason']}"},
            {"stage": "observe", "detail": f"short_turns={len(stm.turns)} long_recall={len(recalled)} preferences={len(changed_preferences)}"},
        ]

        result_payload: Dict[str, Any] = {}
        citations: List[Dict[str, Any]] = []
        if route["mode"] == "quality_review":
            answer, result_payload, citations = self._answer_quality_review()
            trace.append({"stage": "action", "detail": "quality_review_artifacts"})
        elif route["mode"] == "report_run" and orchestrator is not None:
            trace.append({"stage": "action", "detail": "start_multi_agent_report_run"})
            result_payload = orchestrator.run(
                research_topic=text,
                symbol=symbol or "AAPL",
                period=period or latest_completed_period(),
                execution_mode=execution_mode,
                fast=fast,
                search_engines=engines or [],
                enable_remote_data=bool(enable_remote_data),
                data_source_config_path=data_source_config_path,
            )
            result_payload = _attach_report_status(result_payload, self.output_root)
            answer = "已启动并完成多智能体研报生成。右侧报告、引用、图表和轨迹已刷新。"
            citations = _read_json(self.output_root / "citations.json") or []
            trace.append({"stage": "verify", "detail": f"report_run_complete verification={result_payload.get('verification_passed')}"})
        else:
            answer = self._answer(
                text=text,
                route=route,
                stm=stm,
                preference_context=self.preferences.render_context(user_id) if memory_enabled else "",
                ltm_context=self.long_term.render_context(recalled) if memory_enabled else "",
            )
            trace.append({"stage": "action", "detail": "llm_chat" if self.model.api_key else "mock_chat_fallback"})

        stm.add("assistant", answer)
        if memory_enabled:
            self.long_term.add(
                user_id=user_id,
                content=f"User: {text}\nAssistant: {answer}",
                session_id=session_id,
                symbol=symbol,
                period=period,
                importance=0.65 if route["mode"] in {"report_run", "rag"} else 0.45,
                metadata={"mode": route["mode"], "memory_boundary": DEFAULT_MEMORY_BOUNDARY},
            )

        return {
            "answer": answer,
            "mode": route["mode"],
            "route_reason": route["reason"],
            "session_id": session_id,
            "memory_used": {
                "enabled": bool(memory_enabled),
                "boundary": DEFAULT_MEMORY_BOUNDARY,
                "short_term_turns": len(stm.turns),
                "long_term_recall": recalled,
                "preference_updates": changed_preferences,
            },
            "tool_trace": trace,
            "citations": citations,
            "result": result_payload,
        }

    def _route(self, text: str, allow_report_run: bool) -> Dict[str, str]:
        lowered = text.lower()
        report_terms = ["研报", "财报", "报告", "run report", "research report", "company report"]
        generation_terms = ["生成", "写", "撰写", "出一份", "最新", "generate", "create", "run", "write"]
        rag_terms = ["根据报告", "引用", "证据", "检索", "知识库", "复盘", "评测", "rag", "source", "citation"]
        tool_terms = ["天气", "时间", "search_web", "工具", "tool"]
        parsed = parse_chat_task(text)
        if allow_report_run and (parsed.should_run or (any(term in lowered for term in report_terms) and any(term in lowered for term in generation_terms))):
            return {"mode": "report_run", "reason": "report generation intent"}
        if any(term in lowered for term in rag_terms):
            return {"mode": "rag", "reason": "knowledge/evidence retrieval intent"}
        if any(term in lowered for term in tool_terms):
            return {"mode": "tool_call", "reason": "tool-like intent; v1 answers through chat unless report run is requested"}
        return {"mode": "chat", "reason": "general dialogue"}

    def _answer_quality_review(self) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
        latest_dirs = self._latest_valid_run_dirs()
        if latest_dirs is None:
            answer = (
                "当前没有可复盘的已完成报告。"
                "请先完成一次报告生成，再让我读取质量门禁与引用结果。"
            )
            return answer, {"status": "empty"}, []

        output_dir, report_dir = latest_dirs
        summary = _read_json(output_dir / "run_summary.json") or {}
        quality_report = _read_json(output_dir / "quality_report.json") or {}
        delivery_gate = _read_json(output_dir / "delivery_gate.json") or {}
        verification_report = _read_json(output_dir / "verification_report.json") or {}
        evidence_coverage = _read_json(output_dir / "evidence_coverage.json") or {}
        official_manifest = _read_json(output_dir / "official_evidence_manifest.json") or {}
        claims = _read_json(output_dir / "claims.json") or []
        citations = _read_json(output_dir / "citations.json") or []

        blockers: List[str] = []
        for issue in delivery_gate.get("issues", []) if isinstance(delivery_gate, dict) else []:
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity") or "").lower()
            if severity in {"fatal", "blocker"}:
                message = str(issue.get("message") or "").strip()
                if message:
                    blockers.append(message)
        evidence_gaps = verification_report.get("evidence_gaps", []) if isinstance(verification_report, dict) else []
        claim_citation_gaps = 0
        if isinstance(claims, list):
            claim_citation_gaps = sum(
                1
                for item in claims
                if isinstance(item, dict)
                and not list(item.get("evidence_ids") or [])
            )

        status = "通过" if delivery_gate.get("delivery_pass") is True else "未通过"
        lines = [
            f"最近有效报告：{summary.get('symbol', '')} {summary.get('period', '')}",
            f"交付门禁：{status}",
            f"客观质量分：{quality_report.get('total_score', 'N/A')}",
            f"Verifier通过：{verification_report.get('passed', False)}",
            f"缺证据claim数：{len(evidence_gaps) if isinstance(evidence_gaps, list) else 0}",
            f"缺引用claim数：{claim_citation_gaps}",
        ]
        if blockers:
            lines.append("阻塞问题：" + " | ".join(blockers[:3]))
        if delivery_gate.get("delivery_pass") is not True:
            lines.append("建议：先修复 blocker/fatal，再重跑 delivery gate。")
        lines.append("边界说明：以上判断仅基于最近报告 artifacts，不引入新外部事实。")
        if evidence_coverage:
            lines.append(
                "Official evidence coverage: "
                f"{evidence_coverage.get('coverage_status', 'unknown')}; "
                f"three_statements={evidence_coverage.get('has_three_statements', False)}; "
                f"pdf_page_anchors={evidence_coverage.get('pdf_page_anchor_count', 0)}"
            )
        answer = "\n".join(lines)
        payload = {
            "status": "ok",
            "output_dir": str(output_dir),
            "report_dir": str(report_dir),
            "summary": summary if isinstance(summary, dict) else {},
            "quality_report": quality_report if isinstance(quality_report, dict) else {},
            "delivery_gate": delivery_gate if isinstance(delivery_gate, dict) else {},
            "verification_report": verification_report if isinstance(verification_report, dict) else {},
            "evidence_coverage": evidence_coverage if isinstance(evidence_coverage, dict) else {},
            "official_evidence_manifest": official_manifest if isinstance(official_manifest, dict) else {},
            "claim_count": len(claims) if isinstance(claims, list) else 0,
            "citation_count": len(citations) if isinstance(citations, list) else 0,
        }
        return answer, payload, citations if isinstance(citations, list) else []

    def _latest_valid_run_dirs(self) -> Tuple[Path, Path] | None:
        pointer = _read_json(self.output_root / "latest_run.json") or {}
        if isinstance(pointer, dict):
            output_dir = Path(str(pointer.get("output_dir") or ""))
            report_dir = Path(str(pointer.get("report_dir") or ""))
            if self._is_valid_run_dir(output_dir, report_dir):
                return output_dir, report_dir

        output_runs = self.output_root / "runs"
        report_runs = self.report_root / "runs"
        if not output_runs.exists() or not report_runs.exists():
            return None
        candidates: List[Tuple[str, float, Path, Path]] = []
        for run_dir in output_runs.iterdir():
            output_dir = run_dir / "outputs"
            report_dir = report_runs / run_dir.name / "reports"
            if not self._is_valid_run_dir(output_dir, report_dir):
                continue
            try:
                key_match = re.match(r"(\d{8}_\d{6})", run_dir.name)
                time_key = key_match.group(1) if key_match else ""
                mtime = max(output_dir.stat().st_mtime, report_dir.stat().st_mtime)
                candidates.append((time_key, mtime, output_dir, report_dir))
            except OSError:
                continue
        if not candidates:
            return None
        _key, _mtime, output_dir, report_dir = max(candidates, key=lambda item: (item[0], item[1]))
        return output_dir, report_dir

    @staticmethod
    def _is_valid_run_dir(output_dir: Path, report_dir: Path) -> bool:
        if not output_dir.exists() or not report_dir.exists():
            return False
        if not (output_dir / "run_summary.json").exists():
            return False
        return any((report_dir / name).exists() for name in ("report.md", "report.html", "report.json"))

    def _answer(
        self,
        text: str,
        route: Dict[str, str],
        stm: ShortTermChatMemory,
        preference_context: str,
        ltm_context: str,
    ) -> str:
        system = "\n".join(
            part
            for part in [
                "你是 FinSight 金融研究工作台的对话助手。",
                "回答要简洁、可执行。涉及事实、行情、财务数据时，必须说明需要 evidence_id/数据源验证。",
                DEFAULT_MEMORY_BOUNDARY,
                preference_context,
                ltm_context,
            ]
            if part
        )
        messages = [{"role": "system", "content": system}]
        for turn in stm.turns[-8:]:
            messages.append({"role": turn.role, "content": turn.content})
        response = self.model.chat(messages=messages)
        if response.success:
            return response.content.strip() or "我已经收到。"
        context_hint = ""
        if route["mode"] == "rag":
            context_hint = " 当前没有可用模型响应，已保留你的检索意图；正式报告事实仍需 evidence_id 支撑。"
        return f"已收到：{text[:180]}。{context_hint}".strip()


def _resolve_chat_profile(config_path: str) -> str:
    config = load_config(config_path)
    routes = config.get("agent_model_routes") if isinstance(config, dict) else {}
    defaults = routes.get("defaults", {}) if isinstance(routes, dict) and isinstance(routes.get("defaults"), dict) else {}
    chat_route = routes.get("chat") if isinstance(routes, dict) else None
    if isinstance(chat_route, dict):
        return str(chat_route.get("delivery") or chat_route.get("preview") or defaults.get("delivery") or "flash")
    if isinstance(chat_route, str):
        return chat_route
    return str(defaults.get("delivery") or "flash")


def _looks_like_quality_review_text(text: str) -> bool:
    lowered = str(text or "").lower()
    terms = [
        "检查最近报告",
        "复盘最近报告",
        "质量问题",
        "引用是否完整",
        "delivery gate",
        "quality review",
        "quality gate",
        "verification report",
        "citation gap",
    ]
    return any(term in lowered for term in terms)


def _extract_preferences(text: str) -> List[Dict[str, Any]]:
    rules = [
        ("name", r"(?:我叫|我的名字是|称呼我为)\s*([^，。,.!！?\n]{1,24})", 0.95),
        ("likes", r"(?:我喜欢|我爱|偏好)\s*([^，。,.!！?\n]{1,80})", 0.85),
        ("default_requirement", r"(?:以后默认|之后默认|默认)\s*([^，。,.!！?\n]{1,100})", 0.9),
        ("report_style", r"(?:报告风格|写作风格|输出风格)\s*([^，。,.!！?\n]{1,80})", 0.86),
    ]
    output: List[Dict[str, Any]] = []
    for key, pattern, confidence in rules:
        match = re.search(pattern, text)
        if match:
            output.append({"key": key, "value": _clean(match.group(1), 120), "confidence": confidence, "source": "rule"})
    if "用中文" in text:
        output.append({"key": "language", "value": "zh-CN", "confidence": 0.92, "source": "rule"})
    if "用英文" in text:
        output.append({"key": "language", "value": "en", "confidence": 0.92, "source": "rule"})
    if "详细" in text and ("报告" in text or "回答" in text):
        output.append({"key": "detail_level", "value": "detailed", "confidence": 0.78, "source": "rule"})
    if "简洁" in text and ("报告" in text or "回答" in text):
        output.append({"key": "detail_level", "value": "concise", "confidence": 0.78, "source": "rule"})
    return [item for item in output if item["value"]]


def _should_replace_preference(prior: Dict[str, Any], new: Dict[str, Any]) -> bool:
    if not prior:
        return True
    if new.get("source") == "rule" and prior.get("source") != "rule":
        return True
    return float(new.get("confidence", 0.0) or 0.0) >= float(prior.get("confidence", 0.0) or 0.0)


def _tf_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = sum(min(left_tokens.get(token, 0), right_tokens.get(token, 0)) for token in left_tokens)
    denom = math.sqrt(sum(value * value for value in left_tokens.values())) * math.sqrt(
        sum(value * value for value in right_tokens.values())
    )
    if denom == 0:
        return 0.0
    return min(1.0, overlap / denom)


def _tokens(text: str) -> Dict[str, int]:
    parts = re.findall(r"[A-Za-z0-9_.-]+|[\u4e00-\u9fff]{1,3}", str(text).lower())
    counts: Dict[str, int] = {}
    for part in parts:
        counts[part] = counts.get(part, 0) + 1
    return counts


def _recency_score(value: str) -> float:
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    days = max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)
    return math.exp(-days / 30.0)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _attach_report_status(result_payload: Dict[str, Any], output_root: Path) -> Dict[str, Any]:
    output = dict(result_payload) if isinstance(result_payload, dict) else {}
    summary = _read_json(output_root / "run_summary.json")
    verification = _read_json(output_root / "verification_report.json")
    if "verification_passed" not in output and isinstance(summary, dict):
        output["verification_passed"] = bool(summary.get("verification_passed", False))
    if "verifier_passed" not in output and isinstance(verification, dict):
        output["verifier_passed"] = bool(verification.get("passed", False))
    return output


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clean(text: str, limit: int = 500) -> str:
    return " ".join(str(text or "").replace("\n", " ").split())[:limit].rstrip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[compressed]"


def _safe_key(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value).strip())
    return cleaned or "default"
