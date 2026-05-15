"""Durable memory helpers for multi-agent report runs.

This module stores compact run summaries as historical context. Durable memory
must never replace evidence, citations, or verifier gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class DurableMemoryConfig:
    """Runtime settings for durable memory."""

    enabled: bool = False
    root: str = "memory"
    max_context_chars: int = 1600
    max_domain_items: int = 12
    max_episodic_items: int = 6


class DurableMemoryStore:
    """File-backed durable memory store for report runs."""

    def __init__(self, root: str | Path = "memory", max_domain_items: int = 12, max_episodic_items: int = 6):
        self.root = Path(root)
        self.max_domain_items = int(max_domain_items)
        self.max_episodic_items = int(max_episodic_items)

    def build_context_brief(
        self,
        symbol: str,
        period: str,
        report_type: str = "company_stock_report",
        max_chars: int = 1600,
    ) -> str:
        """Build a bounded historical context brief for Planner/Router prompts."""

        symbol_key = _key(symbol)
        period_key = _key(period)
        domain = self._read_json(self._domain_path(symbol_key))
        episodes = self._read_recent_episodes(symbol_key=symbol_key, period_key=period_key)

        lines: List[str] = [
            "[DurableMemory]",
            "Historical context only. Do not use this as evidence. Every factual report claim still needs current evidence_id citations.",
            f"Scope: report_type={report_type}, symbol={symbol}, period={period}",
        ]
        domain_items = domain.get("items", []) if isinstance(domain, dict) else []
        if domain_items:
            lines.append("Domain notes:")
            for item in domain_items[-self.max_domain_items :]:
                text = _clean_text(str(item.get("text", "")) if isinstance(item, dict) else str(item), 240)
                if text:
                    lines.append(f"- {text}")

        if episodes:
            lines.append("Recent run notes:")
            for episode in episodes[-self.max_episodic_items :]:
                if not isinstance(episode, dict):
                    continue
                decision = _clean_text(str(episode.get("decision", "")), 120)
                metrics = episode.get("quality_metrics", {}) if isinstance(episode.get("quality_metrics"), dict) else {}
                metric_text = ", ".join(f"{key}={value}" for key, value in sorted(metrics.items()) if value is not None)
                note = _clean_text(str(episode.get("summary", "")), 220)
                parts = [part for part in [decision, metric_text, note] if part]
                if parts:
                    lines.append(f"- {'; '.join(parts)}")

        return _truncate("\n".join(lines), max_chars)

    def persist_run(
        self,
        state: Dict[str, Any],
        run_summary: Dict[str, Any],
        report_type: str = "company_stock_report",
    ) -> Dict[str, str]:
        """Persist working, episodic, and domain memory artifacts."""

        symbol = str(run_summary.get("symbol") or state.get("symbol") or "").upper()
        period = str(run_summary.get("period") or state.get("period") or "")
        run_id = self._run_id(symbol=symbol, period=period, topic=str(run_summary.get("research_topic", "")))
        snapshot = self._snapshot(run_id=run_id, state=state, run_summary=run_summary, report_type=report_type)

        working_path = self.root / "working" / run_id / "snapshot.json"
        episodic_path = self.root / "episodic" / _key(symbol) / _key(period) / f"{run_id}.json"
        domain_path = self._domain_path(_key(symbol))

        self._write_json(working_path, snapshot)
        self._write_json(episodic_path, snapshot)
        domain_payload = self._update_domain_memory(domain_path=domain_path, snapshot=snapshot)

        return {
            "run_id": run_id,
            "working_snapshot": str(working_path),
            "episodic_snapshot": str(episodic_path),
            "domain_memory": str(domain_path),
            "domain_item_count": str(len(domain_payload.get("items", []))),
        }

    def _read_recent_episodes(self, symbol_key: str, period_key: str) -> List[Dict[str, Any]]:
        folder = self.root / "episodic" / symbol_key / period_key
        if not folder.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for path in sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime):
            payload = self._read_json(path)
            if isinstance(payload, dict):
                rows.append(payload)
        return rows[-self.max_episodic_items :]

    def _snapshot(
        self,
        run_id: str,
        state: Dict[str, Any],
        run_summary: Dict[str, Any],
        report_type: str,
    ) -> Dict[str, Any]:
        verification = state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {}
        scorecard = state.get("company_report_scorecard", {}) if isinstance(state.get("company_report_scorecard"), dict) else {}
        summary = _clean_text(str(run_summary.get("research_topic", "")), 260)
        return {
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "report_type": report_type,
            "symbol": str(run_summary.get("symbol") or state.get("symbol") or "").upper(),
            "period": str(run_summary.get("period") or state.get("period") or ""),
            "summary": summary,
            "decision": "verification_passed" if verification.get("passed", False) else "verification_not_passed",
            "quality_metrics": {
                "verification_passed": verification.get("passed"),
                "claim_count": run_summary.get("claim_count"),
                "citation_count": run_summary.get("citation_count"),
                "chart_count": run_summary.get("chart_count"),
                "overall_score": run_summary.get("company_report_overall_score") or scorecard.get("overall_score"),
            },
            "conversation_context": state.get("conversation_context", {}),
            "verifier_feedback": verification.get("errors", []) if isinstance(verification.get("errors", []), list) else [],
            "open_gap_count": run_summary.get("evidence_gap_count"),
        }

    def _update_domain_memory(self, domain_path: Path, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._read_json(domain_path)
        if not isinstance(payload, dict):
            payload = {}
        items = payload.get("items", []) if isinstance(payload.get("items"), list) else []
        metric_text = ", ".join(
            f"{key}={value}"
            for key, value in sorted(snapshot.get("quality_metrics", {}).items())
            if value is not None
        )
        text = _clean_text(
            f"{snapshot.get('symbol')} {snapshot.get('period')} {snapshot.get('decision')}; {metric_text}",
            300,
        )
        row = {"run_id": snapshot.get("run_id"), "created_at": snapshot.get("created_at"), "text": text}
        items = [item for item in items if isinstance(item, dict) and item.get("run_id") != row["run_id"]]
        items.append(row)
        payload = {
            "symbol": snapshot.get("symbol"),
            "updated_at": snapshot.get("created_at"),
            "items": items[-self.max_domain_items :],
        }
        self._write_json(domain_path, payload)
        return payload

    def _domain_path(self, symbol_key: str) -> Path:
        return self.root / "domain" / f"{symbol_key}.json"

    def _run_id(self, symbol: str, period: str, topic: str) -> str:
        source = f"{symbol}|{period}|{topic}|{datetime.now(timezone.utc).isoformat()}"
        return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in str(value).strip())
    return cleaned or "unknown"


def _clean_text(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    return cleaned[:limit].rstrip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[compressed]"
