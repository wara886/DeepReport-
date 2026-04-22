# Diagnostic Ablation Comparison

- run_id: diag_20260418
- primary_variant: bm25_real_writer
- baseline_summary: reports\eval_v1\summary.json

## Side-by-Side

| scenario | verifier | writer_hit | numeric_matcher | grounded_rate | writer_hit_rate_proxy | numeric_accuracy |
|---|---|---|---|---:|---:|---:|
| baseline_diag | on | top3 | strict | 0.5 | 1.0 | 0.75 |
| verifier_off_diag | off | top3 | strict | 1.0 | 1.0 | 0.75 |
| writer_top1_diag | on | top1 | strict | 0.5 | 0.0 | 0.75 |
| numeric_relaxed_diag | on | top3 | relaxed | 0.5 | 1.0 | 1.0 |

## Notes

- This is diagnostic-only ablation on existing artifacts.
- No retrieval/writer/verifier core logic is modified.