# Spot Check 根因模板（Root-Cause Template）

字段填写建议：

- root_cause_primary: retrieval|verifier|writer|numeric_extractor|data_contract|other
- failure_stage: retrieval|rerank|claim_build|verifier|writer_render|numeric_match
- evidence_issue_type: missing_evidence|wrong_source|top1_bias|id_mapping|none
- numeric_issue_type: value_mismatch|unit_mismatch|period_mismatch|unsupported|none
- verifier_issue_type: threshold_too_high|claim_confidence_bias|rule_conflict|none
- is_systematic: yes|no

- template_csv: reports\eval_v1_diagnostics\diag_20260418_cn_final\spot_check_10_root_cause_template.csv