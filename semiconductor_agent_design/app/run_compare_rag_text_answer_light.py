from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.agent.company_profiles import get_company_profile
from app.agent.llm import call_llm
from app.agent.semiconductor_prompt import make_semiconductor_system_prompt
from app.agent.tech_potential import assess_technology_potential


QUESTION_DEFAULT = "2026년 5월 29일 삼성전자의 HBM4E 샘플 출하 발표는 삼성전자와 SK하이닉스의 7~30일 주가에 어떤 영향을 줄까?"


def _plain_answer(question: str) -> str:
    system = make_semiconductor_system_prompt(
        mode="plain_text_answer_comparison_light",
        use_rag=False,
        output_format="Answer in Korean with concise sections.",
    )
    user = f"""질문:
{question}

아래 형식으로 한국어 답변:
1. 결론
2. 기술 해석
3. 회사별 차별화
4. 7~30일 주가 영향
5. 핵심 근거 3개
6. 리스크 2개

조건:
- 일반 지식만 사용
- 실제 문서를 본 것처럼 말하지 말 것
- 반도체 전문가 톤으로 답하되 보수적으로 답할 것"""
    return call_llm(system, user).strip()


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        title = " ".join(str(item.get("title", "")).lower().split())
        source = str(item.get("source", "")).lower().strip()
        if not title:
            continue
        key = (title, source)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _short_profiles(company: str) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for code in [company, "000660", "005930"]:
        code = str(code or "").strip().upper()
        if not code:
            continue
        prof = get_company_profile(code)
        if prof and all(existing.get("code") != prof.get("code") for existing in profiles):
            profiles.append(
                {
                    "code": prof.get("code"),
                    "name_ko": prof.get("name_ko"),
                    "role_ko": prof.get("role_ko"),
                    "core_businesses_ko": prof.get("core_businesses_ko", [])[:3],
                    "why_it_moves_ko": prof.get("why_it_moves_ko", [])[:3],
                }
            )
    return profiles


def _agent_answer(question: str, company: str, domain: str, top_k: int) -> tuple[str, dict[str, Any]]:
    assessment = assess_technology_potential(question, company_hint=company, domain_hint=domain, top_k=top_k)
    evidence_items = _dedupe(((assessment.evidence_pack or {}).get("items", []) if isinstance(assessment.evidence_pack, dict) else []) or [])
    normalized_event = ((assessment.evidence_pack or {}).get("normalized_event") if isinstance(assessment.evidence_pack, dict) else {}) or {}

    evidence_lines = []
    for idx, item in enumerate(evidence_items[:4], start=1):
        evidence_lines.append(
            f"[E{idx}] {item.get('title','')} | source={item.get('source','')} | "
            f"company={item.get('company','') or '-'} | domain={item.get('domain','') or '-'} | "
            f"score={float(item.get('evidence_score', 0.0) or 0.0):.3f}"
        )

    summary = {
        "recommendation": assessment.recommendation,
        "confidence": assessment.confidence,
        "reasoning_confidence": assessment.reasoning_confidence,
        "catalyst_imminence": assessment.catalyst_imminence,
        "bottleneck": assessment.bottleneck,
        "novelty": assessment.novelty,
        "revenue_linkage": assessment.revenue_linkage,
        "market_transmission_speed": assessment.market_transmission_speed,
        "company_impact": assessment.company_impact,
        "evidence_quality": assessment.evidence_quality,
        "normalized_event": normalized_event,
        "overall_thesis": assessment.overall_thesis,
        "company_profiles": _short_profiles(company),
        "evidence_used": [
            {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "source_type": item.get("source_type", ""),
                "company": item.get("company", ""),
                "domain": item.get("domain", ""),
                "published_at": item.get("published_at", ""),
                "evidence_score": item.get("evidence_score", 0.0),
            }
            for item in evidence_items[:4]
        ],
    }

    system = make_semiconductor_system_prompt(
        mode="rag_grounded_text_answer_comparison_light",
        use_rag=True,
        output_format="Answer in Korean with concise sections.",
    )
    user = f"""질문:
{question}

구조화 판단:
{json.dumps(summary, ensure_ascii=False)}

핵심 증거:
{chr(10).join(evidence_lines)}

아래 형식으로 한국어 답변:
1. 결론
2. 기술 해석
3. 회사별 차별화
4. 7~30일 주가 영향
5. 핵심 근거 3개
6. 리스크 2개
7. 사용한 근거 출처 요약

조건:
- 일반론 말고 반도체 전문가처럼 해석
- HBM4E를 메모리 세대 전환, 고객 qualification, 공급 가시성, 경쟁구도 측면에서 해석
- 삼성전자와 SK하이닉스를 반드시 다르게 설명
- 같은 증거를 반복 나열하지 말 것"""
    answer = call_llm(system, user).strip()
    return answer, summary


def _render_md(question: str, plain: str, agent: str, summary: dict[str, Any]) -> str:
    event = summary.get("normalized_event") or {}
    evidence = summary.get("evidence_used") or []
    evidence_quality = summary.get("evidence_quality") or {}
    impact = summary.get("company_impact") or []

    lines = [
        "# LLM vs Semiconductor Agent Comparison",
        "",
        f"- Question: {question}",
        "",
        "## LLM Only",
        plain,
        "",
        "## Semiconductor Agent",
        agent,
        "",
        "## Normalized Technology Event",
        f"- Event type: `{event.get('event_type', 'n/a')}`",
        f"- Technology: `{event.get('technology', 'n/a')}`",
        f"- Event date: `{event.get('event_date', 'n/a')}`",
        f"- Company: `{event.get('related_company', 'n/a')}`",
        f"- Domain: `{event.get('related_domain', 'n/a')}`",
        "",
        "## Company Impact",
    ]
    if impact:
        for item in impact:
            lines.append(
                f"- {item.get('company','')}({item.get('code','')}): `{item.get('stance','')}` @ {float(item.get('confidence', 0.0)):.2f} - {item.get('reason','')}"
            )
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Evidence Used (Deduplicated)",
            f"- Evidence grade: `{evidence_quality.get('grade', 'n/a')}`",
            f"- Evidence count: `{evidence_quality.get('count', 0)}`",
            f"- Source count: `{evidence_quality.get('source_count', 0)}`",
        ]
    )
    for item in evidence:
        lines.append(
            f"- `{item.get('source_type','')}/{item.get('source','')}`: {item.get('title','')} "
            f"(company={item.get('company','') or '-'}, domain={item.get('domain','') or '-'}, "
            f"published_at={item.get('published_at','') or '-'}, score={float(item.get('evidence_score', 0.0) or 0.0):.3f})"
        )

    lines.extend(["", "## Structured Summary", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="?", default=QUESTION_DEFAULT)
    parser.add_argument("--company", default="005930")
    parser.add_argument("--domain", default="hbm")
    parser.add_argument("--top-k", type=int, default=4)
    parser.add_argument("--save", required=True)
    args = parser.parse_args()

    plain = _plain_answer(args.question)
    agent, summary = _agent_answer(args.question, args.company, args.domain, args.top_k)
    md = _render_md(args.question, plain, agent, summary)
    path = Path(args.save)
    path.write_text(md, encoding="utf-8")
    print(md)
    print()
    print(f"[saved] {path}")


if __name__ == "__main__":
    main()
