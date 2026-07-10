"""Utilities for keeping mojibake out of user-facing report artifacts."""

from __future__ import annotations

from typing import Any
import copy
import re


MOJIBAKE_PATTERNS = [
    r"璐㈠姟",
    r"缁撹",
    r"鐮旂┒",
    r"鎵ц",
    r"璇佹嵁",
    r"鏀跺叆",
    r"鍑€",
    r"涓夎",
    r"鍚岃",
    r"浼板€",
    r"椋庨櫓",
    r"鎶曡祫",
    r"\u7480\u3220\u59df",  # common mojibake for finance labels
    r"\u7470\u52e1",
    r"\u93b5\u8fbc",
    r"\u93c0\u8dfa",
    r"\u942e\u65df",
    r"\u93c2",
    r"\u6dc7",
    r"\u942e",
    r"\u7f01\u64b9",
    r"\u9431\u65c2",
    r"\u934f\u6350",
    r"\u9359\u5084",
    r"\u93b5\u8fbc",
    r"\u6d93\u535e",
    r"\u7487\u4f79\u5d41",
    r"璐靛",
    r"鑼呭",
    r"浜夊",
    r"鈥",
    r"\ufffd",
]


def looks_like_mojibake(value: Any) -> bool:
    """Return True when text has common Chinese UTF-8 mojibake markers."""

    text = str(value or "")
    if not text:
        return False
    return any(re.search(pattern, text) for pattern in MOJIBAKE_PATTERNS)


def repair_known_mojibake_text(value: Any) -> Any:
    """Repair only unambiguous short labels; leave long prose to quality gates."""

    if not isinstance(value, str) or not value:
        return value
    replacements = {
        "\u7480\u3220\u59df": "\u8d22\u52a1",
        "\u7470\u52e1": "\u89c4\u6a21",
        "\u7f01\u64b9\u8b91": "\u7ed3\u8bba",
        "\u7f03\u3224\u4fe1\u6434": "\u7f6e\u4fe1\u5ea6",
        "\u93c0\u8dfa\u53c6": "\u6536\u5165",
        "\u934f\u20ac\u9352\u2570\u9f0e": "\u51c0\u5229\u6da6",
        "\u7f01\u5fda\u60c0\u941c\u9593\u567e\u6d7c": "\u7ecf\u8425\u73b0\u91d1\u6d41",
        "\u6d5c\u579a\u5393\u6d5c\u70d8\u7691\u5e09": "\u4ebf\u5143\u4eba\u6c11\u5e01",
        "\u93b5\u8fbc\u3221\u93bd\u6a3f\u59de": "\u6267\u884c\u6458\u8981",
        "\u934f\u6350\u303e": "\u56fe\u8868",
        "\u9359\u5084\u20ac\u5198\u6f75\u59e7": "\u53c2\u8003\u6765\u6e90",
        "\u93c1\u65c2\u2532": "\u7814\u7a76",
        "\u7487\u4f79\u5d41": "\u8bc1\u636e",
    }
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    lowered = value.lower()
    if lowered == "financial_scale":
        return "\u8d22\u52a1\u89c4\u6a21"
    if lowered == "claim_confidence":
        return "\u7ed3\u8bba\u7f6e\u4fe1\u5ea6"
    if "revenue" == lowered:
        return "\u6536\u5165"
    if "net_income" == lowered:
        return "\u51c0\u5229\u6da6"
    if "operating_cash_flow" == lowered:
        return "\u7ecf\u8425\u73b0\u91d1\u6d41"
    return value


def repair_known_mojibake_obj(value: Any) -> Any:
    """Deep-copy an object and repair known short mojibake labels in leaves."""

    if isinstance(value, dict):
        return {key: repair_known_mojibake_obj(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_known_mojibake_obj(item) for item in value]
    if isinstance(value, tuple):
        return tuple(repair_known_mojibake_obj(item) for item in value)
    return repair_known_mojibake_text(copy.deepcopy(value))


def build_mojibake_quality_issue(artifact_name: str, text: Any) -> dict[str, str] | None:
    """Build a quality issue when an artifact still contains mojibake."""

    if not looks_like_mojibake(text):
        return None
    return {
        "issue_id": f"mojibake_{artifact_name}",
        "severity": "blocker",
        "category": "mojibake_policy",
        "message": f"{artifact_name} contains Chinese mojibake markers; regenerate or repair before delivery.",
    }
