from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.agent.models import TechnologyPotentialAssessment
from app.agent.tech_potential import (
    assess_technology_potential,
    assess_technology_potential_without_rag,
)


def _to_assessment(obj: dict[str, Any] | TechnologyPotentialAssessment, *, topic: str, company: str, domain: str) -> TechnologyPotentialAssessment:
    if isinstance(obj, TechnologyPotentialAssessment):
        return obj

    payload = dict(obj or {})
    payload.setdefault("topic", topic)
    payload.setdefault("company_hint", company)
    payload.setdefault("domain_hint", domain)
    payload.setdefault("as_of", "")
    payload.setdefault("catalyst_imminence", {})
    payload.setdefault("bottleneck", {})
    payload.setdefault("company_impact", [])
    payload.setdefault("evidence_quality", {})
    payload.setdefault("novelty", {})
    payload.setdefault("revenue_linkage", {})
    payload.setdefault("market_transmission_speed", {})
    payload.setdefault("longevity", {})
    payload.setdefault("overall_thesis", "")
    payload.setdefault("red_flags", [])
    payload.setdefault("missing_data", [])
    payload.setdefault("recommendation", "")
    payload.setdefault("confidence", 0.0)
    payload.setdefault("reasoning_confidence", 0.0)
    payload.setdefault("reasoning_breakdown", {})
    payload.setdefault("supporting_evidence", [])
    payload.setdefault("evidence_pack", {})
    return TechnologyPotentialAssessment(**payload)


def _summary_lines(title: str, a: TechnologyPotentialAssessment) -> list[str]:
    catalyst = a.catalyst_imminence or {}
    bottleneck = a.bottleneck or {}
    novelty = a.novelty or {}
    revenue = a.revenue_linkage or {}
    transmission = a.market_transmission_speed or {}
    evidence = a.evidence_quality or {}

    lines = [
        f"## {title}",
        f"- Recommendation: `{a.recommendation or 'n/a'}`",
        f"- Confidence: `{a.confidence:.2f}` / reasoning `{a.reasoning_confidence:.2f}`",
        f"- Catalyst Imminence: `{catalyst.get('dominant_window', 'n/a')}`",
        f"- Bottleneck Importance: `{bottleneck.get('importance', 'n/a')}`",
        f"- Novelty: `{novelty.get('surprise_level', 'n/a')}` / `{novelty.get('market_awareness', 'n/a')}`",
        f"- Revenue Linkage: `{revenue.get('link_strength', 'n/a')}` -> `{revenue.get('time_to_monetize', 'n/a')}`",
        f"- Market Transmission Speed: `{transmission.get('speed', 'n/a')}`",
        f"- Evidence Quality: `{evidence.get('grade', 'n/a')}`",
        f"- Thesis: {a.overall_thesis or 'n/a'}",
    ]
    if a.company_impact:
        impacts = ", ".join(
            f"{item.get('company','')}({item.get('code','')}):{item.get('stance','')}@{float(item.get('confidence', 0.0)):.2f}"
            for item in a.company_impact[:5]
        )
        lines.append(f"- Company Impact: {impacts}")
    if a.supporting_evidence:
        lines.append("- Evidence:")
        for item in a.supporting_evidence[:5]:
            lines.append(
                f"  - {item.get('source_type','')}/{item.get('source','')}: {item.get('title','')} "
                f"(score={float(item.get('evidence_score', 0.0)):.3f})"
            )
    return lines


def _delta_lines(base: TechnologyPotentialAssessment, rag: TechnologyPotentialAssessment) -> list[str]:
    base_e = base.evidence_quality or {}
    rag_e = rag.evidence_quality or {}
    return [
        "## What Changed",
        f"- Evidence quality: `{base_e.get('grade', 'n/a')} -> {rag_e.get('grade', 'n/a')}`",
        f"- Evidence count: `{base_e.get('count', 0)} -> {rag_e.get('count', 0)}`",
        f"- Source count: `{base_e.get('source_count', 0)} -> {rag_e.get('source_count', 0)}`",
        f"- Reasoning confidence: `{base.reasoning_confidence:.2f} -> {rag.reasoning_confidence:.2f}`",
        f"- Recommendation: `{base.recommendation or 'n/a'} -> {rag.recommendation or 'n/a'}`",
    ]


def render_compare_markdown(
    topic: str,
    baseline: TechnologyPotentialAssessment,
    rag: TechnologyPotentialAssessment,
) -> str:
    lines: list[str] = [
        "# LLM vs RAG Comparison",
        "",
        f"- Topic: {topic}",
        "",
    ]
    lines.extend(_summary_lines("LLM Only", baseline))
    lines.append("")
    lines.extend(_summary_lines("RAG + LLM", rag))
    lines.append("")
    lines.extend(_delta_lines(baseline, rag))
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Compare plain LLM vs RAG-backed semiconductor-agent answers.")
    parser.add_argument("topic", help="Question or topic to compare")
    parser.add_argument("--company", default="", help="Optional company hint, e.g. 000660")
    parser.add_argument("--domain", default="", help="Optional domain hint, e.g. hbm / litho / packaging")
    parser.add_argument("--top-k", type=int, default=8, help="RAG evidence count")
    parser.add_argument("--save", default="", help="Optional output markdown path")
    parser.add_argument("--json", action="store_true", help="Also print structured JSON payload")
    args = parser.parse_args()

    baseline_raw = assess_technology_potential_without_rag(
        args.topic,
        company_hint=args.company,
        domain_hint=args.domain,
    )
    rag_assessment = assess_technology_potential(
        args.topic,
        company_hint=args.company,
        domain_hint=args.domain,
        top_k=args.top_k,
    )

    baseline = _to_assessment(baseline_raw, topic=args.topic, company=args.company, domain=args.domain)
    rag = _to_assessment(rag_assessment, topic=args.topic, company=args.company, domain=args.domain)

    md = render_compare_markdown(args.topic, baseline, rag)
    print(md)

    if args.json:
        payload = {
            "topic": args.topic,
            "baseline": asdict(baseline),
            "rag": asdict(rag),
        }
        print()
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    if args.save:
        path = Path(args.save)
        path.write_text(md, encoding="utf-8")
        print()
        print(f"[saved] {path}")


if __name__ == "__main__":
    main()
