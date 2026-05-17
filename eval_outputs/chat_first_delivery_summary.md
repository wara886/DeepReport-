# Chat-first Delivery Rerun Summary

Run date: 2026-05-17

Config: `configs/model_backends_local_ollama.yaml`

## 600519.SS

- Prompt: `generate 600519.SS latest company report`
- Period: `2026Q1`
- Report: `eval_outputs/chat_first_delivery_600519SS_latest/company/reports/report.html`
- Verifier: `true`
- Objective: `false`, score `0.992`
- LLM review: `false`, score `0.0`
- Delivery: `false`
- Top issue: objective blocker `同行对比只有框架或待补说明，缺少可读结论`
- Remediation plan generated: `true`

## AMD

- Prompt: `generate AMD latest company report`
- Period: `2026Q1`
- Report: `eval_outputs/chat_first_delivery_AMD_latest/company/reports/report.html`
- Verifier: `true`
- Objective: `false`, score `0.9415`
- LLM review: `false`, score `0.0`
- Delivery: `false`
- Top issues:
  - objective blocker `同行对比只有框架或待补说明，缺少可读结论`
  - objective blocker `估值缺失但没有明确估值不可用原因`
  - verifier blocker `None`
  - objective warning `权威/一手来源占比偏低：0.33`
- Remediation plan generated: `true`

## Conclusion

Commit 16 rerun did not reach `delivery_pass=true`. The remaining blockers are concrete quality gates rather than generic runtime failure: peer comparison remains too framework-like, AMD valuation still lacks a usable reason/path in the final body, and Ollama-based LLM review returned `0.0`, so `llm_review_pass=false` remains a hard blocker.
