"""Section-level prompt text for future backend generation."""

from __future__ import annotations

from typing import Dict


SECTION_PROMPTS: Dict[str, str] = {
    "executive_summary": "Summarize the most material findings and confidence.",
    "business_overview": "Describe business context and evidence coverage.",
    "financial_analysis": "Present numeric findings and claim-level evidence links.",
    "valuation": "State comparative signals and ranking rationale.",
    "risks": "Summarize risk signals and uncertainty clearly.",
    "conclusion": "Provide concise final takeaways and caveats.",
}


def get_section_prompt(section_name: str) -> str:
    return SECTION_PROMPTS.get(section_name, "Provide concise, evidence-linked summary.")

