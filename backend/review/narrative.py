"""
backend/review/narrative.py
===========================
Gemini narrative for the fixed-schema review report. Reuses the same
GeminiClient (JSON mode, retries, number-guard) from backend/llm.py
— only the prompts and section list differ, because the categories differ
(A-E instead of E1-F1).

    from backend.review.narrative import StatementNarrativeAgent
    agent = StatementNarrativeAgent()
    report = agent.run(review_report)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from backend.llm import GeminiClient, extract_numbers as _extract_numbers

OUTPUT_CONTRACT = """
Reply with ONLY a JSON object, no markdown fences, in exactly this shape:
{"heading": "<6 words max>", "commentary": "<2-3 sentences>", "risk_level": "LOW|MEDIUM|HIGH"}

Rules:
- Use ONLY the numbers given above. Do not calculate new ones.
- Do not invent figures not stated.
- Write like an audit reviewer: factual, specific, no filler.
"""


def _fails(report: Dict[str, Any], category_prefix: str) -> List[Dict[str, Any]]:
    return [f for f in report["findings"]
            if f["category"].startswith(category_prefix) and f["status"] == "FAIL"]


def _warns(report: Dict[str, Any], category_prefix: str) -> List[Dict[str, Any]]:
    return [f for f in report["findings"]
            if f["category"].startswith(category_prefix) and f["status"] == "WARN"]


def section_a_math(report: Dict[str, Any]) -> Tuple[str, List[str], str]:
    fails = _fails(report, "A.")
    warns = _warns(report, "A.")
    lines = [f"- {f['period']} {f['rule']}: expected {f['expected']}, "
             f"found {f['found']}, difference {f['delta']}"
             for f in fails[:6]] or ["- none"]
    facts = [str(len(fails)), str(len(warns))] + [str(f['delta']) for f in fails[:6]]

    prompt = f"""You are reviewing {report['company_name']}'s financial statements.
{len(fails)} mathematical accuracy checks failed, {len(warns)} were rounding warnings.

Failures:
{chr(10).join(lines)}

Write the mathematical accuracy summary for an audit workpaper.
{OUTPUT_CONTRACT}"""

    fallback = (f"{len(fails)} mathematical accuracy check(s) failed and "
                f"{len(warns)} fell within the rounding tolerance. "
                + (f"The largest discrepancy was {max(fails, key=lambda f: abs(f['delta']))['delta']:+,.0f} crore."
                   if fails else "All identities held."))
    return prompt, facts, fallback


def section_b_consistency(report: Dict[str, Any]) -> Tuple[str, List[str], str]:
    fails = _fails(report, "B.")
    lines = [f"- {f['period']} {f['rule']}: expected {f['expected']}, "
             f"found {f['found']}, difference {f['delta']}"
             for f in fails] or ["- none"]
    facts = [str(len(fails))] + [str(f['delta']) for f in fails]

    prompt = f"""You are reviewing {report['company_name']}.
{len(fails)} internal consistency checks failed — these compare figures that
should agree across different statements (e.g. profit on the income statement
vs cash flow, or cash balances vs the balance sheet).

Failures:
{chr(10).join(lines)}

Write the internal consistency summary for an audit workpaper.
{OUTPUT_CONTRACT}"""

    fallback = (f"{len(fails)} cross-statement consistency check(s) failed. "
                f"These compare figures that should agree across different "
                f"statements and often indicate a figure was updated in one "
                f"place but not another.")
    return prompt, facts, fallback


def section_c_prior_year(report: Dict[str, Any]) -> Tuple[str, List[str], str]:
    fails = _fails(report, "C.")
    lines = [f"- {f['period']} {f['statement']}: filed {f['expected']}, "
             f"currently shown {f['found']}, difference {f['delta']}"
             for f in fails] or ["- none"]
    facts = [str(len(fails))] + [str(f['delta']) for f in fails]

    prompt = f"""You are reviewing {report['company_name']}.
{len(fails)} prior-year tie-out check(s) failed — the comparative figures in
the current statements do not match what was filed last year.

Failures:
{chr(10).join(lines)}

Write the prior-year tie-out summary for an audit workpaper. Note that an
undisclosed restatement is a serious finding regardless of amount.
{OUTPUT_CONTRACT}"""

    fallback = (f"{len(fails)} prior-year comparative(s) did not match what "
                f"was previously filed. " +
                (f"The largest was {max(fails, key=lambda f: abs(f['delta']))['statement']}."
                 if fails else "All comparatives tied out."))
    return prompt, facts, fallback


def section_d_ratios(report: Dict[str, Any]) -> Tuple[str, List[str], str]:
    fails = _fails(report, "D.")
    lines = [f"- {f['period']} {f['rule']}: published {f['found']}, "
             f"recomputed {f['expected']}"
             for f in fails] or ["- none"]
    facts = [str(len(fails))] + [str(f['expected']) for f in fails] + [str(f['found']) for f in fails]

    prompt = f"""You are reviewing {report['company_name']}.
{len(fails)} published ratio(s) disagree with our independent recalculation.

Disagreements:
{chr(10).join(lines)}

Write the ratio verification summary for an audit workpaper.
{OUTPUT_CONTRACT}"""

    fallback = (f"{len(fails)} published ratio(s) did not match our "
                f"independent recalculation from the underlying statements.")
    return prompt, facts, fallback


def section_e_text(report: Dict[str, Any]) -> Tuple[str, List[str], str]:
    issues = [f for f in report["findings"] if f["category"].startswith("E.")]
    lines = [f"- {i['statement']}: {i['note']}" for i in issues] or ["- none"]
    facts = [str(len(issues))]

    prompt = f"""You are reviewing {report['company_name']}.
{len(issues)} spelling or grammar issue(s) were found in line-item labels and
narrative disclosures.

Issues:
{chr(10).join(lines)}

Write the spelling and grammar summary for an audit workpaper.
{OUTPUT_CONTRACT}"""

    fallback = (f"{len(issues)} spelling or grammar issue(s) were identified "
                f"in line-item labels and disclosure notes.")
    return prompt, facts, fallback


SECTIONS = {
    "A": ("Mathematical Accuracy", section_a_math),
    "B": ("Internal Consistency", section_b_consistency),
    "C": ("Prior Year Tie-Out", section_c_prior_year),
    "D": ("Ratio Verification", section_d_ratios),
    "E": ("Spelling and Grammar", section_e_text),
}


class StatementNarrativeAgent:
    """Builds narrative commentary for every category of the review report."""

    def __init__(self, client: GeminiClient = None) -> None:
        self.client = client or GeminiClient()

    def _build(self, code: str, heading: str, prompt: str,
              allowed: List[str], fallback: str) -> Dict[str, Any]:
        section = {
            "section_code": code, "heading": heading, "commentary": fallback,
            "risk_level": "LOW", "source": "template", "number_check": "PASS",
            "unverified_numbers": [],
        }
        if not self.client.enabled:
            section["source"] = "template_no_api_key"
            return section
        try:
            reply = self.client.generate_json(prompt)
        except Exception as exc:
            section["source"] = f"template_fallback ({type(exc).__name__})"
            return section

        commentary = str(reply.get("commentary", "")).strip()
        if not commentary:
            section["source"] = "template_fallback (empty reply)"
            return section

        risk = str(reply.get("risk_level", "LOW")).upper()
        section.update({
            "commentary": commentary,
            "heading": str(reply.get("heading") or heading).strip(),
            "risk_level": risk if risk in ("LOW", "MEDIUM", "HIGH") else "LOW",
            "source": f"gemini:{self.client.model}",
        })

        supplied = {n for fact in allowed for n in _extract_numbers(str(fact))}
        written = _extract_numbers(commentary)
        invented = sorted({n for n in written if n not in supplied})
        if invented:
            section["number_check"] = "FLAGGED"
            section["unverified_numbers"] = invented
        return section

    def run(self, review_report: Dict[str, Any]) -> Dict[str, Any]:
        sections = []
        for code, (heading, builder) in SECTIONS.items():
            prompt, allowed, fallback = builder(review_report)
            sections.append(self._build(code, heading, prompt, allowed, fallback))

        generated = sum(1 for s in sections if s["source"].startswith("gemini"))
        flagged = sum(1 for s in sections if s["number_check"] == "FLAGGED")

        return {
            "company_name": review_report["company_name"],
            "model": self.client.model if self.client.enabled else None,
            "ai_enabled": self.client.enabled,
            "summary": {"sections": len(sections), "ai_generated": generated,
                       "template_fallback": len(sections) - generated,
                       "number_check_flagged": flagged},
            "sections": sections,
        }