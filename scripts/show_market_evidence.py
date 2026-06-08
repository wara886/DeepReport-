"""Read sample evidence from each market and display structure."""
import json
from pathlib import Path

for market in ['A_SHARE', 'HK', 'US']:
    path = Path(f'data/market_simulation/{market}/evidence.json')
    if not path.exists():
        continue
    ev = json.loads(path.read_text(encoding='utf-8'))
    print(f'\n{"="*60}')
    print(f'{market} — {len(ev)} evidence records')
    print(f'{"="*60}')
    if not ev:
        print('  (empty)')
        continue
    for i, item in enumerate(ev[:4]):
        src = item.get('source_type', item.get('engine', '?'))
        content = str(item.get('content', item.get('snippet', '')))[:300]
        print(f'\n  [{i}] source_type={src}')
        print(f'      evidence_id={item.get("evidence_id", "?")}')
        print(f'      content: {content[:200]}')

    # Check for additional evidence from PDF chunks
    chunks_path = path.parent / 'pdf_section_chunks.jsonl'
    if chunks_path.exists():
        chunks = [json.loads(l) for l in chunks_path.read_text(encoding='utf-8').strip().split('\n') if l.strip()]
        print(f'\n  --- PDF Chunks: {len(chunks)} chunks ---')
        for i, c in enumerate(chunks[:2]):
            txt = str(c.get('content', c.get('text', '')))[:200]
            print(f'    chunk {i}: {txt}')

    # Check sec_10k sections for US
    if market == 'US':
        aa_path = path.parent / 'analysis_artifacts.json'
        if aa_path.exists():
            aa = json.loads(aa_path.read_text(encoding='utf-8'))
            for sec_key in ['annual_report_sections', 'sec_annual_report_sections']:
                sections = aa.get(sec_key, {}) if isinstance(aa, dict) else {}
                if isinstance(sections, dict) and sections:
                    items = list(sections.items())[:2]
                    print(f'\n  --- {sec_key}: {len(sections)} items ---')
                    for k, v in items:
                        txt = str(v)[:200] if isinstance(v, str) else json.dumps(v, ensure_ascii=False)[:200]
                        print(f'    {k}: {txt}')

    # Check PDF extraction audit for A_SHARE
    if market == 'A_SHARE':
        audit_path = path.parent / 'pdf_extraction_audit.json'
        if audit_path.exists():
            audit = json.loads(audit_path.read_text(encoding='utf-8'))
            keys = list(audit.keys())[:5] if isinstance(audit, dict) else []
            print(f'\n  --- PDF Extraction Audit keys: {keys} ---')
            for k in keys:
                v = audit[k]
                txt = json.dumps(v, ensure_ascii=False)[:200]
                print(f'    {k}: {txt}')

print(f'\n{"="*60}')
print('Done')
