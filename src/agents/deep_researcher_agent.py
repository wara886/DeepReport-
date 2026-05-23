"""DeepResearcherAgent for evidence discovery."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.react_loop import run_react_tool_loop
from src.models import ModelAdapter
from src.search import SearchManager
from src.tools import ToolRegistry, build_core_tool_registry


class DeepResearcherAgent(BaseAgent):
    """Find and rank evidence for downstream financial analysis agents."""

    def __init__(
        self,
        model: ModelAdapter | None = None,
        search_manager: SearchManager | None = None,
        tool_registry: ToolRegistry | None = None,
        tools: Dict[str, Any] | None = None,
    ):
        self.tool_registry = tool_registry or build_core_tool_registry()
        super().__init__(name="DeepResearcherAgent", model=model, tools=tools or self.tool_registry.handlers())
        self.search_manager = search_manager or SearchManager.with_local_sources()

    def get_capabilities(self) -> List[str]:
        return [
            "search financial evidence sources",
            "aggregate local and remote search results",
            "return ranked evidence candidates for analysis and browser agents",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        query = str(task.parameters.get("query") or task.description)
        topk = int(task.parameters.get("topk", 5))
        engines = task.parameters.get("engines")
        if engines is not None and not isinstance(engines, list):
            engines = [item.strip() for item in str(engines).split(",") if item.strip()]
        react_attempted = bool(task.parameters.get("use_react", False))
        skill_brief = str(task.parameters.get("skill_brief", "")).strip()

        try:
            if react_attempted and self.model and hasattr(self.model, "chat"):
                react_payload = self._run_react_search(task=task, query=query, topk=topk, skill_brief=skill_brief)
                candidates = react_payload.get("evidence_candidates", [])
                if candidates:
                    if not bool(task.parameters.get("merge_standard_search_after_react", False)):
                        return self.success(
                            task,
                            {
                                "query": query,
                                "evidence_candidates": candidates[:topk],
                                "search_meta": react_payload.get("search_meta", {}),
                            },
                            metadata={
                                "hit_count": len(candidates[:topk]),
                                "react_used": True,
                                "standard_search_merged": False,
                                "react_trace": react_payload.get("react_trace", []),
                                "react_final_content": react_payload.get("final_content", ""),
                                "skill_brief_chars": len(skill_brief),
                            },
                        )
                    fallback_payload = self._run_standard_search(task=task, query=query, topk=topk, engines=engines)
                    candidates = _merge_evidence_candidates(candidates, fallback_payload.get("hits", []))[:topk]
                    search_meta = dict(fallback_payload.get("meta", {}))
                    search_meta["react_tool_loop"] = react_payload.get("search_meta", {})
                    search_meta["react_merged_with_standard_search"] = True
                    return self.success(
                        task,
                        {
                            "query": query,
                            "evidence_candidates": candidates[:topk],
                            "search_meta": search_meta,
                        },
                        metadata={
                            "hit_count": len(candidates[:topk]),
                            "react_used": True,
                            "standard_search_merged": True,
                            "react_trace": react_payload.get("react_trace", []),
                            "react_final_content": react_payload.get("final_content", ""),
                            "skill_brief_chars": len(skill_brief),
                        },
                    )
            payload = self._run_standard_search(task=task, query=query, topk=topk, engines=engines)
            return self.success(
                task,
                {
                    "query": payload["query"],
                    "evidence_candidates": payload["hits"],
                    "search_meta": payload["meta"],
                },
                metadata={
                    "hit_count": len(payload.get("hits", [])),
                    "engines": payload.get("meta", {}).get("engines", []),
                    "engine_meta": payload.get("meta", {}).get("engine_meta", {}),
                    "react_attempted": react_attempted,
                    "react_used": False,
                    "skill_brief_chars": len(skill_brief),
                },
            )
        except Exception as exc:
            return self.failure(task, str(exc))

    def _run_standard_search(
        self,
        task: AgentTask,
        query: str,
        topk: int,
        engines: List[str] | None = None,
    ) -> Dict[str, Any]:
        return self.search_manager.search(
            query=query,
            topk=topk,
            engines=engines,
            symbol=task.parameters.get("symbol"),
            period=task.parameters.get("period"),
            curated_dir=task.parameters.get("curated_dir", "data/curated"),
            raw_data_root=task.parameters.get("raw_data_root", "data/raw/real_data"),
            ranking_mode=task.parameters.get("ranking_mode", "bm25"),
            data_source_config_path=task.parameters.get("data_source_config_path", "configs/data_sources.yaml"),
            enable_remote=bool(task.parameters.get("enable_remote", False)),
        )

    def _run_react_search(self, task: AgentTask, query: str, topk: int, skill_brief: str = "") -> Dict[str, Any]:
        allowed_tools = ["retrieve_local_evidence", "fetch_yahoo_market_snapshot"]
        schemas = [self.tool_registry.get(name).to_tool_schema() for name in allowed_tools]
        handlers = dict(self.tool_registry.handlers())
        skill_block = f"Relevant skills:\n{skill_brief}\n" if skill_brief else ""
        retrieve_handler = handlers.get("retrieve_local_evidence")
        if retrieve_handler:
            handlers["retrieve_local_evidence"] = lambda **kwargs: retrieve_handler(
                symbol=kwargs.pop("symbol", task.parameters.get("symbol")),
                period=kwargs.pop("period", task.parameters.get("period")),
                ranking_mode=kwargs.pop("ranking_mode", task.parameters.get("ranking_mode", "hybrid_rerank")),
                use_chunks=kwargs.pop("use_chunks", task.parameters.get("use_chunks", True)),
                **kwargs,
            )

        result = run_react_tool_loop(
            model=self.model,
            system_prompt=(
                "You are DeepResearcherAgent. Choose financial evidence tools when useful. "
                "Stop when enough citation-ready evidence has been observed."
            ),
            user_prompt=(
                f"Research query: {query}\n"
                f"Symbol: {task.parameters.get('symbol', '')}\n"
                f"Period: {task.parameters.get('period', '')}\n"
                f"TopK: {topk}\n"
                f"Ranking mode: {task.parameters.get('ranking_mode', 'hybrid_rerank')}\n"
                f"{skill_block}"
                "Use retrieve_local_evidence for report facts and fetch_yahoo_market_snapshot for market context."
            ),
            tool_schemas=schemas,
            handlers=handlers,
            max_steps=int(task.parameters.get("react_max_steps", 3) or 3),
        )
        candidates = _evidence_candidates_from_observations(result.get("observations", []))
        return {
            "evidence_candidates": candidates,
            "search_meta": {
                "engines": ["react_tool_loop"],
                "react_success": bool(result.get("success", False)),
                "react_error": result.get("error", ""),
                "tool_calls": [item.get("tool_name") for item in result.get("trace", [])],
            },
            "react_trace": result.get("trace", []),
            "final_content": result.get("final_content", ""),
        }


def _evidence_candidates_from_observations(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        result = observation.get("result", {}) if isinstance(observation, dict) else {}
        rows: List[Dict[str, Any]] = []
        if isinstance(result, dict) and isinstance(result.get("hits"), list):
            rows.extend(item for item in result["hits"] if isinstance(item, dict))
        if isinstance(result, dict) and isinstance(result.get("evidence"), dict):
            evidence = result["evidence"]
            rows.append(
                {
                    "result_id": evidence.get("evidence_id"),
                    "title": evidence.get("title") or evidence.get("source_type") or "Market snapshot",
                    "snippet": evidence.get("content", ""),
                    "url": evidence.get("source_url", ""),
                    "source_type": evidence.get("source_type", ""),
                    "score": 1.0,
                    "raw": evidence,
                }
            )
        for row in rows:
            key = str(row.get("result_id") or row.get("evidence_id") or row.get("url") or row.get("source_url"))
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append(row)
    return candidates


def _merge_evidence_candidates(primary: List[Dict[str, Any]], secondary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in primary + secondary:
        if not isinstance(row, dict):
            continue
        key = str(row.get("result_id") or row.get("evidence_id") or row.get("url") or row.get("source_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged
