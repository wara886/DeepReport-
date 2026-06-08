"""Check PDF chunk content in detail."""
import json
from pathlib import Path

samples = [
    ("A_SHARE/run2_225928_with_pdf", "A_SHARE run2 PDF chunks (68 lines)"),
    ("A_SHARE/run3_093638_fy2024", "A_SHARE run3 PDF chunks (6 lines)"),
]

for subdir, label in samples:
    path = Path(f"data/market_simulation_15/{subdir}/pdf_section_chunks.jsonl")
    print(f"\n--- {label} ---")
    if not path.exists():
        print("  NOT FOUND")
        continue
    lines = [l for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
    print(f"  Lines: {len(lines)}")
    if lines:
        for i, line in enumerate(lines[:5]):
            data = json.loads(line)
            content = str(data.get("content", data.get("text", "")))
            print(f"  line {i}: content_len={len(content)}  source_type={data.get('source_type','?')}")
            if len(content) > 10:
                print(f"     preview: {content[:200]}")
            else:
                print(f"     (empty or too short)")

    # Also check pdf_section_summaries
    sums_path = path.parent / "pdf_section_summaries.json"
    if sums_path.exists():
        sums = json.loads(sums_path.read_text(encoding="utf-8"))
        print(f"\n  pdf_section_summaries: {list(sums.keys())[:5] if isinstance(sums, dict) else 'not-a-dict'}")

    # Check pdf_extraction_audit
    audit_path = path.parent / "pdf_extraction_audit.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if isinstance(audit, dict):
            print(f"  pdf_extraction_audit keys: {list(audit.keys())[:8]}")
            for k in list(audit.keys())[:5]:
                v = audit[k]
                if isinstance(v, str):
                    print(f"    {k}: {v[:200]}")
                elif isinstance(v, list):
                    print(f"    {k}: {len(v)} items")
                    if v:
                        print(f"      first: {str(v[0])[:200]}")
