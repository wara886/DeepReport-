"""统一日志配置 — stdlib logging + TaskIDAdapter。

用法
----
    from src.utils.logging import configure_logging, get_task_logger

    # 在 pipeline 入口处初始化
    configure_logging(log_dir="logs", run_name="batch_20260601")

    # 在模块中获取带 task_id 的 logger
    log = get_task_logger(__name__, task_id="fetch_600519.SS_FY2025")
    log.info("开始下载 PDF")  # → 2026-06-01 12:00:00 | INFO     | fetch_600519.SS_FY2025 | __main__ | 开始下载 PDF
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from logging import LogRecord
from pathlib import Path
from typing import Any, Optional

# ── 格式常量 ─────────────────────────────────────

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(task_id)s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


# ── TaskID 注入 ──────────────────────────────────

class TaskIDAdapter(logging.LoggerAdapter):
    """LoggerAdapter 自动向每条日志注入 task_id。

    用法:
        log = TaskIDAdapter(logging.getLogger(__name__), {"task_id": "my_task_001"})
        log.info("hello")  # 输出中自动带上 task_id
    """

    def process(
        self, msg: Any, kwargs: Any
    ) -> tuple[Any, Any]:
        kwargs.setdefault("extra", {})
        kwargs["extra"]["task_id"] = self.extra.get("task_id", "-")
        return msg, kwargs


def get_task_logger(name: str, task_id: str = "-") -> TaskIDAdapter:
    """获取带 task_id 上下文的 LoggerAdapter。

    Args:
        name: logger name，通常传 __name__
        task_id: 当前任务标识

    Returns:
        绑定了 task_id 的 LoggerAdapter
    """
    base = logging.getLogger(name)
    return TaskIDAdapter(base, {"task_id": task_id})


# ── 兼容 Formatter（处理缺失 task_id 的情况）───────

class _SafeFormatter(logging.Formatter):
    """Formatter 在 LogRecord 缺少 task_id 时不崩溃，自动回退到 '-'。"""

    def format(self, record: LogRecord) -> str:
        if not hasattr(record, "task_id"):
            record.task_id = "-"
        return super().format(record)


# ── 配置 ─────────────────────────────────────────

_LOG_CONFIGURED: set[str] = set()


def configure_logging(
    log_dir: str | Path = "logs",
    run_name: Optional[str] = None,
    console_level: int = logging.INFO,
    file_level: int = logging.DEBUG,
    reset: bool = False,
) -> str:
    """配置根 logger：同时写控制台 + pipeline.log + errors.log。

    Args:
        log_dir: 日志根目录
        run_name: 运行名称（默认 auto-gen）
        console_level: 控制台日志级别
        file_level: 文件日志级别
        reset: 是否清空已有 handler（用于测试/重置）

    Returns:
        实际使用的 run_name
    """
    resolved = run_name or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    if resolved in _LOG_CONFIGURED and not reset:
        return resolved

    log_path = Path(log_dir) / resolved
    log_path.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    if reset:
        root_logger.handlers.clear()
    elif root_logger.handlers:
        # 已有配置，不重复添加
        _LOG_CONFIGURED.add(resolved)
        return resolved

    root_logger.setLevel(logging.DEBUG)

    # ── 控制台 handler（INFO+） ──
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(console_level)
    console.setFormatter(_SafeFormatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(console)

    # ── 全量文件 handler（DEBUG+） ──
    all_handler = logging.FileHandler(
        log_path / "pipeline.log", encoding="utf-8"
    )
    all_handler.setLevel(file_level)
    all_handler.setFormatter(_SafeFormatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(all_handler)

    # ── 错误汇总文件（ERROR+） ──
    err_handler = logging.FileHandler(
        log_path / "errors.log", encoding="utf-8"
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(_SafeFormatter(LOG_FORMAT, DATE_FORMAT))
    root_logger.addHandler(err_handler)

    _LOG_CONFIGURED.add(resolved)
    return resolved


# ── 便捷函数 ────────────────────────────────────

def log_vector_search(
    logger: TaskIDAdapter,
    query: str,
    topk: int,
    results_count: int,
    scores: list[float],
    collection: str = "",
    **extra: Any,
) -> None:
    """统一打印向量检索相似度日志（当前完全缺失的功能）。"""
    score_str = ", ".join(f"{s:.3f}" for s in scores[:10])
    parts = [
        f"vector_search | query=\"{query[:60]}\"",
        f"topk={topk}",
        f"results={results_count}",
        f"scores=[{score_str}]",
    ]
    if collection:
        parts.append(f"collection={collection}")
    for k, v in extra.items():
        parts.append(f"{k}={v}")
    logger.info(" | ".join(parts))
