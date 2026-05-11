import csv
import json
from pathlib import Path

from src.evaluation.per_claim_verification import export_per_claim_verification


def test_export_per_claim_verification_outputs(tmp_path: Path):
    claim_path = tmp_path / "claim_table.json"
    ckpt_path = tmp_path / "verifier_checkpoint.json"
    claim_path.write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_1",
                    "claim_text": "Revenue near 100.0B.",
                    "section_name": "financial_analysis",
                    "confidence": 0.8,
                    "evidence_ids": ["ev_1"],
                    "numeric_values": {"revenue_billion": 100.0},
                    "notes": "ok",
                },
                {
                    "claim_id": "cl_2",
                    "claim_text": "Margin near 10.0%.",
                    "section_name": "valuation",
                    "confidence": 0.7,
                    "evidence_ids": [],
                    "numeric_values": {},
                    "notes": "",
                },
            ]
        ),
        encoding="utf-8",
    )
    ckpt_path.write_text(json.dumps({"confidence_threshold": 0.75}), encoding="utf-8")

    outputs = export_per_claim_verification(
        claim_path=claim_path,
        output_dir=tmp_path,
        checkpoint_path=ckpt_path,
    )

    json_path = Path(str(outputs["per_claim_verification_json"]))
    csv_path = Path(str(outputs["per_claim_verification_csv"]))
    assert json_path.exists()
    assert csv_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["threshold"] == 0.75
    assert payload["rule"] == "is_grounded = confidence >= threshold"
    assert payload["claim_count"] == 2
    assert payload["grounded_count"] == 1

    row1 = payload["rows"][0]
    row2 = payload["rows"][1]
    assert row1["is_grounded"] is True
    assert row2["is_grounded"] is False
    assert row2["review_priority"] == "high"
    assert "is_grounded = confidence(0.7000) >= threshold(0.7500)" in row2["notes"]

    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert rows[0]["threshold"] == "0.75"
    assert rows[1]["is_grounded"] == "False"
