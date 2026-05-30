"""Test: verify pack_claims drops business_overview, governance, strategy claims."""
import json, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

claims = json.load(open(
    "data/outputs/multi_agent/claims.json", encoding="utf-8"
))

from src.agents.context_packer import pack_claims

packed, meta = pack_claims(claims, max_items=10, text_limit=400, total_chars=10000)

print(f"Total claims: {len(claims)}")
print(f"Packed claims: {len(packed)}")

packed_sections = {}
for c in packed:
    s = c.get("section_name", "?")
    packed_sections.setdefault(s, []).append(c.get("claim_id", "?"))
    print(f"  {c['claim_id']}: section={s}, conf={c.get('confidence', 0)}")

print(f"\nDropped claims: {len(meta.get('dropped_ids', []))}")
dropped_sections = {}
for c in claims:
    if c["claim_id"] in meta.get("dropped_ids", []):
        s = c.get("section_name", "?")
        dropped_sections.setdefault(s, []).append(c["claim_id"])
        print(f"  DROPPED {c['claim_id']}: section={s}, conf={c.get('confidence', 0)}, text={c.get('claim_text','')[:60]}")

print(f"\nSections in packed: {set(s for s in packed_sections.keys())}")
print(f"Sections dropped entirely: {set(s for s in dropped_sections.keys()) - set(s for s in packed_sections.keys())}")
