"""Detailed analysis of market-specific evidence structure."""
import json
from pathlib import Path

# --- A_SHARE: read PDF section chunks and summaries ---
print('=' * 60)
print('A_SHARE: PDF Section Chunks (sample)')
print('=' * 60)

chunks_path = Path('data/market_simulation/A_SHARE/pdf_section_chunks.jsonl')
if chunks_path.exists():
    chunks = [json.loads(l) for l in chunks_path.read_text(encoding='utf-8').strip().split('\n') if l.strip()]
    print(f'Total chunks: {len(chunks)}')
    for i, chunk in enumerate(chunks[:4]):
        content = str(chunk.get('content', chunk.get('text', '')))[:400]
        meta = {k: v for k, v in chunk.items() if k not in ('content', 'text')}
        print(f'\n--- Chunk {i} ---')
        print(f'  Meta: {json.dumps(meta, ensure_ascii=False)[:200]}')
        print(f'  Content: {content}')

summaries_path = Path('data/market_simulation/A_SHARE/pdf_section_summaries.json')
if summaries_path.exists():
    summaries = json.loads(summaries_path.read_text(encoding='utf-8'))
    secs = summaries.get('sections', summaries) if isinstance(summaries, dict) else {}
    print(f'\n\nTotal PDF section summaries: {len(secs)}')
    for k, v in list(secs.items())[:4]:
        txt = str(v)[:300] if isinstance(v, str) else json.dumps(v, ensure_ascii=False)[:300]
        print(f'\n  [{k}]: {txt}')

print('\n')
print('=' * 60)
print('A_SHARE: Full evidence records')
print('=' * 60)
ev_path = Path('data/market_simulation/A_SHARE/evidence.json')
if ev_path.exists():
    ev = json.loads(ev_path.read_text(encoding='utf-8'))
    for i, item in enumerate(ev):
        content = str(item.get('content', ''))[:400]
        keys = list(item.keys())
        print(f'\n[{i}] id={item.get("evidence_id","")}  type={item.get("source_type","")}')
        print(f'    keys: {keys}')
        print(f'    content: {content}')

# --- US: read SEC 10-K sections ---
print('\n')
print('=' * 60)
print('US: SEC 10-K Section Content')
print('=' * 60)
aa_path = Path('data/market_simulation/US/analysis_artifacts.json')
if aa_path.exists():
    aa = json.loads(aa_path.read_text(encoding='utf-8'))
    ars = aa.get('annual_report_sections', {})
    if ars:
        print(f'Total annual_report_sections: {len(ars)} keys')
        for k, v in list(ars.items())[:6]:
            txt = str(v)[:400]
            print(f'\n  [{k}]: {txt}')

# Also read sec_10k_section evidence
ev_path_us = Path('data/market_simulation/US/evidence.json')
if ev_path_us.exists():
    ev_us = json.loads(ev_path_us.read_text(encoding='utf-8'))
    sec_ev = [e for e in ev_us if e.get('source_type') == 'sec_10k_section']
    print(f'\n\nUS: SEC-typed evidence ({len(sec_ev)} items)')
    for i, item in enumerate(sec_ev[:4]):
        content = str(item.get('content', ''))[:400]
        print(f'\n[{i}] evidence_id={item.get("evidence_id","")}')
        print(f'    content: {content}')

# --- HK: show available data ---
print('\n')
print('=' * 60)
print('HK: Full evidence records')
print('=' * 60)
ev_path_hk = Path('data/market_simulation/HK/evidence.json')
if ev_path_hk.exists():
    ev_hk = json.loads(ev_path_hk.read_text(encoding='utf-8'))
    for i, item in enumerate(ev_hk):
        content = str(item.get('content', ''))[:400]
        print(f'\n[{i}] id={item.get("evidence_id","")}  type={item.get("source_type","")}')
        print(f'    content: {content}')

print('\n\nDone.')
