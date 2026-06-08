"""Phase 1 验证脚本 — 重跑 10 个验证 run 确认修链效果。

用法:
    python scripts/rerun_15_validation.py                    # 全量 10 run（较慢）
    python scripts/rerun_15_validation.py --quick             # 仅跑 3 个代表性 run（A+H+US 各一）
    python scripts/rerun_15_validation.py --symbol 600519.SS  # 仅跑指定公司
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ── 10 个验证 run ──
RUNS = [
    ("600519.SS", "FY2025"),
    ("600519.SS", "2026Q1"),
    ("600519.SS", "FY2024"),
    ("0700.HK", "FY2025"),
    ("0700.HK", "2026Q1"),
    ("TSLA", "FY2025"),
    ("AAPL", "FY2025"),
    ("NVDA", "FY2025"),
    ("GOOGL", "FY2025"),
    ("AMD", "2026Q1"),
]

QUICK_RUNS = [
    ("600519.SS", "FY2025"),  # A 股代表
    ("0700.HK", "FY2025"),    # 港股代表
    ("TSLA", "FY2025"),       # 美股代表
]


def run_single(symbol: str, period: str, output_dir: str, report_dir: str, fast: bool = True) -> dict:
    """通过 subprocess 调用 run_multi_agent_demo.py。"""
    cmd = [
        sys.executable, "-m", "scripts.run_multi_agent_demo",
        "--symbol", symbol,
        "--period", period,
        "--output-dir", output_dir,
        "--report-dir", report_dir,
    ]
    if fast:
        cmd.append("--fast")

    print(f"  ▶ 启动 {symbol} {period} ...")
    start = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.time() - start

    # 解析结果
    stdout = result.stdout
    stderr = result.stderr
    exit_code = result.returncode

    # 尝试从 stdout 提取 quality score
    quality_score = None
    for line in stdout.splitlines():
        if "total_score" in line.lower() or "quality" in line.lower():
            try:
                import re
                m = re.search(r"([\d.]+)", line)
                if m:
                    quality_score = float(m.group(1))
            except ValueError:
                pass

    summary = {
        "symbol": symbol,
        "period": period,
        "exit_code": exit_code,
        "elapsed_sec": round(elapsed, 1),
        "quality_score": quality_score,
        "stdout_tail": "\n".join(stdout.strip().splitlines()[-20:]),
        "stderr_tail": "\n".join(stderr.strip().splitlines()[-20:]),
        "success": exit_code == 0,
    }

    status = "✅" if summary["success"] else "❌"
    print(f"  {status} {symbol} {period} 完成 ({elapsed:.0f}s) score={quality_score}")

    return summary


def verify_run_outputs(symbol: str, period: str, output_dir: str) -> dict:
    """验证一个 run 的产出文件。"""
    run_dir = _find_run_dir(output_dir, symbol, period)
    if not run_dir:
        return {"found": False, "error": "run_dir_not_found"}

    checks = {}
    evidence_file = run_dir / "evidence.json"
    pdf_audit_file = run_dir / "pdf_extraction_audit.json"
    quality_file = run_dir / "quality_report.json"

    # Evidence 检查
    if evidence_file.exists():
        with open(evidence_file, "r", encoding="utf-8") as f:
            evidence = json.load(f)
        total_hits = len(evidence)
        non_empty = sum(1 for e in evidence if e.get("content", "").strip())
        # 检查是否有 mojibake
        mojibake_count = 0
        from src.report.fact_extractors.pdf_encoding import has_mojibake
        for e in evidence:
            if has_mojibake(e.get("content", "")):
                mojibake_count += 1
        checks["evidence"] = {
            "total": total_hits,
            "non_empty": non_empty,
            "mojibake_count": mojibake_count,
        }
    else:
        checks["evidence"] = {"error": "evidence.json not found"}

    # PDF audit 检查
    if pdf_audit_file.exists():
        with open(pdf_audit_file, "r", encoding="utf-8") as f:
            audit = json.load(f)
        checks["pdf_audit"] = {
            "page_count": audit.get("page_count", 0),
            "usable_chunks": audit.get("usable_chunk_count", 0),
            "failure": audit.get("failure_reason", ""),
        }
    else:
        checks["pdf_audit"] = {"error": "pdf_extraction_audit.json not found"}

    # Quality score 检查
    if quality_file.exists():
        with open(quality_file, "r", encoding="utf-8") as f:
            quality = json.load(f)
        checks["quality"] = {
            "total_score": quality.get("total_score"),
            "objective_pass": quality.get("objective_pass"),
            "threshold": quality.get("quality_threshold"),
        }
    else:
        checks["quality"] = {"error": "quality_report.json not found"}

    return {"found": True, "run_dir": str(run_dir), "checks": checks}


def _find_run_dir(base_dir: str, symbol: str, period: str) -> Path | None:
    """在 output directory 中查找匹配的 run 目录。"""
    base = Path(base_dir)
    if not base.exists():
        return None
    # 按修改时间排序，找最新的
    candidates = sorted(base.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        if not c.is_dir():
            continue
        summary_file = c / "run_summary.json"
        if summary_file.exists():
            with open(summary_file, "r", encoding="utf-8") as f:
                try:
                    summary = json.load(f)
                    if summary.get("symbol") == symbol and summary.get("period") == period:
                        return c
                except (json.JSONDecodeError, Exception):
                    continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 验证 — 重跑 15 组验证 run")
    parser.add_argument("--quick", action="store_true", help="仅跑 3 个代表性 run")
    parser.add_argument("--symbol", default="", help="仅跑指定 ticker（如 600519.SS）")
    parser.add_argument("--output-dir", default="data/outputs/multi_agent")
    parser.add_argument("--report-dir", default="data/reports/multi_agent")
    parser.add_argument("--verification-dir", default="data/validation/phase1")
    parser.add_argument("--skip-run", action="store_true", help="跳过运行，只验证已有产出")
    args = parser.parse_args()

    # 筛选 run 列表
    if args.symbol:
        symbol_upper = args.symbol.upper()
        runs = [(s, p) for s, p in RUNS if s == symbol_upper]
        if not runs:
            print(f"❌ 未找到 ticker {symbol_upper} 的 run 配置")
            return 1
    elif args.quick:
        runs = QUICK_RUNS
    else:
        runs = RUNS

    print(f"{'=' * 60}")
    print(f"Phase 1 验证 — {len(runs)} 个 run")
    print(f"{'=' * 60}")

    verification_dir = Path(args.verification_dir)
    verification_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    exec_results = []
    verify_results = []

    for idx, (symbol, period) in enumerate(runs, 1):
        print(f"\n[{idx}/{len(runs)}] {symbol} {period}")
        print("-" * 40)

        if not args.skip_run:
            result = run_single(symbol, period, args.output_dir, args.report_dir)
            exec_results.append(result)
            if not result["success"]:
                print(f"  ⚠  run 失败，退出码 {result['exit_code']}")

        # 验证产出
        checks = verify_run_outputs(symbol, period, args.output_dir)
        verify_results.append({"symbol": symbol, "period": period, **checks})

        # 打印检查摘要
        if checks.get("found"):
            c = checks["checks"]
            ev = c.get("evidence", {})
            q = c.get("quality", {})
            pdf = c.get("pdf_audit", {})
            print(f"  证据: {ev.get('total', '?')} hits, {ev.get('non_empty', '?')} non-empty, {ev.get('mojibake_count', '?')} mojibake")
            print(f"  PDF: {pdf.get('usable_chunks', '?')} usable / {pdf.get('page_count', '?')} pages")
            print(f"  质量: score={q.get('total_score')} pass={q.get('objective_pass')} threshold={q.get('threshold')}")
        else:
            print(f"  ⚠  产出目录未找到: {checks.get('error')}")

    # ── 汇总报告 ──
    report = {
        "timestamp": timestamp,
        "runs": len(runs),
        "skipped_run": args.skip_run,
        "execution": exec_results,
        "verification": verify_results,
    }

    report_path = verification_dir / f"phase1_validation_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印汇总
    print(f"\n{'=' * 60}")
    print(f"验证报告: {report_path}")
    print(f"{'=' * 60}")

    passed = sum(1 for v in verify_results if v.get("found") and v.get("checks", {}).get("quality", {}).get("objective_pass") is True)
    total_verified = sum(1 for v in verify_results if v.get("found"))
    print(f"通过质量门禁: {passed}/{total_verified}")

    # 量化汇总
    total_evidence = 0
    total_mojibake = 0
    total_non_empty = 0
    for v in verify_results:
        if not v.get("found"):
            continue
        ev = v.get("checks", {}).get("evidence", {})
        if isinstance(ev, dict):
            total_evidence += ev.get("total", 0) or 0
            total_non_empty += ev.get("non_empty", 0) or 0
            total_mojibake += ev.get("mojibake_count", 0) or 0

    print(f"总证据: {total_evidence} | 非空: {total_non_empty} | 含乱码: {total_mojibake}")

    # 与 Phase 0 基线对比建议
    print(f"\n{'=' * 60}")
    print("与 Phase 0 基线对比（手检要点）:")
    print("  1. A 股 600519: PDF chunks 是否不再为空？（原 68/68 空）")
    print("  2. 召回 hits 数是否上升？（原 standalone A 股 2.0/run, 港股 12.7/run）")
    print("  3. mojibake 是否减少？（原 1/4 的 A 股证据含 mojibake）")
    print(f"{'=' * 60}")

    return 0 if passed == total_verified else 1


if __name__ == "__main__":
    sys.exit(main())
