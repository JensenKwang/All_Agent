from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.agent.company_profiles import get_company_profile
from app.agent.llm import call_llm
from app.agent.semiconductor_prompt import make_semiconductor_system_prompt
from app.agent.tech_potential import assess_technology_potential


def _plain_llm_answer(question: str) -> str:
    system = make_semiconductor_system_prompt(
        mode="plain_text_answer_comparison",
        use_rag=False,
        output_format=(
            "Answer directly and clearly in Korean. "
            "Do not pretend to cite documents you did not see."
        ),
    )
    user = f"""질문:
{question}

출력 형식:
1. 결론
2. 기술 해석
   - 이번 사건에서 실제로 무엇이 달라졌는지
   - 어떤 반도체 병목이나 경쟁 포인트와 연결되는지
   - 양산성, 고객 채택, 공급 가시성 관점에서 어떤 의미인지
3. 회사별 차별화
   - 삼성전자와 SK하이닉스를 다르게 봐야 한다면 왜 다른지
4. 7~30일 주가 영향
5. 핵심 근거 3개
6. 리스크 2개

조건:
- 한국어로 답변
- 과장하지 말고 보수적으로 답변
- 실제 문서를 보지 않았다고 가정하고, 일반 지식 기반으로만 답변
- 반도체 전문가처럼 설명하되 출처가 없는 세부 사실은 단정하지 말 것"""
    return call_llm(system, user).strip()


def _dedupe_evidence_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title", "") or "").strip()
        source = str(item.get("source", "") or "").strip()
        key = (" ".join(title.lower().split()), source.lower())
        if not key[0]:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _render_evidence_context(items: list[dict[str, Any]], max_chars: int = 5000) -> str:
    blocks: list[str] = []
    total = 0
    for idx, item in enumerate(items, start=1):
        block = (
            f"[E{idx}] {item.get('title', '')}\n"
            f"- source: {item.get('source', '')}\n"
            f"- source_type: {item.get('source_type', '')}\n"
            f"- company: {item.get('company', '')}\n"
            f"- domain: {item.get('domain', '')}\n"
            f"- published_at: {item.get('published_at', '')}\n"
            f"- score: {float(item.get('evidence_score', 0.0) or 0.0):.3f}\n"
            f"- text: {str(item.get('text', '') or '').strip()}\n"
        )
        if total + len(block) > max_chars and blocks:
            break
        blocks.append(block)
        total += len(block)
    return "\n".join(blocks)


def _company_profiles_from_question(question: str, explicit_company: str = "") -> list[dict[str, Any]]:
    q = str(question or "").lower()
    candidates: list[str] = []
    mapping = {
        "005930": ["005930", "samsung", "삼성전자", "삼성"],
        "000660": ["000660", "sk hynix", "sk하이닉스", "하이닉스"],
        "042700": ["042700", "hanmi", "한미반도체", "한미"],
    }
    if explicit_company:
        candidates.append(str(explicit_company).strip().upper())
    for code, hints in mapping.items():
        if any(h.lower() in q for h in hints):
            candidates.append(code)
    ordered: list[str] = []
    for code in candidates:
        if code and code not in ordered:
            ordered.append(code)
    profiles: list[dict[str, Any]] = []
    for code in ordered[:4]:
        profile = get_company_profile(code)
        if profile:
            profiles.append(profile)
    return profiles


def _rag_answer(question: str, company: str, domain: str, top_k: int) -> tuple[str, dict]:
    assessment = assess_technology_potential(
        question,
        company_hint=company,
        domain_hint=domain,
        top_k=top_k,
    )

    catalyst = assessment.catalyst_imminence or {}
    bottleneck = assessment.bottleneck or {}
    novelty = assessment.novelty or {}
    revenue = assessment.revenue_linkage or {}
    transmission = assessment.market_transmission_speed or {}
    evidence_quality = assessment.evidence_quality or {}
    normalized_event = (assessment.evidence_pack or {}).get("normalized_event", {}) if isinstance(assessment.evidence_pack, dict) else {}

    raw_items = ((assessment.evidence_pack or {}).get("items", []) if isinstance(assessment.evidence_pack, dict) else []) or []
    unique_items = _dedupe_evidence_dicts(raw_items)
    evidence_context = _render_evidence_context(unique_items, max_chars=5000)
    company_profiles = _company_profiles_from_question(question, company)

    structured_summary = {
        "recommendation": assessment.recommendation,
        "confidence": assessment.confidence,
        "reasoning_confidence": assessment.reasoning_confidence,
        "catalyst_imminence": catalyst,
        "bottleneck": bottleneck,
        "novelty": novelty,
        "revenue_linkage": revenue,
        "market_transmission_speed": transmission,
        "company_impact": assessment.company_impact,
        "evidence_quality": evidence_quality,
        "normalized_event": normalized_event,
        "overall_thesis": assessment.overall_thesis,
        "company_profiles": company_profiles,
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
            for item in unique_items[:6]
        ],
    }

    system = make_semiconductor_system_prompt(
        mode="rag_grounded_text_answer_comparison",
        use_rag=True,
        output_format=(
            "Answer directly and clearly in Korean. "
            "Ground the answer in the provided evidence and be explicit about uncertainty."
        ),
    )
    user = f"""질문:
{question}

구조화된 판단:
{json.dumps(structured_summary, ensure_ascii=False, indent=2)}

근거 문서:
{evidence_context}

출력 형식:
1. 결론
2. 기술 해석
   - 이번 사건이 이전 세대/기존 경쟁구도 대비 무엇을 바꿨는지
   - 이 사건이 메모리 병목, 고객 qualification, 공급 가시성, 양산성과 어떻게 연결되는지
   - 단순 '좋은 기술'이 아니라 왜 지금 주가 이벤트가 될 수 있는지
3. 회사별 차별화
   - 삼성전자
   - SK하이닉스
   각 회사가 밸류체인에서 어떤 위치인지 반영해서 다르게 설명
4. 7~30일 주가 영향
5. 핵심 근거 3개
6. 리스크 2개
7. 사용한 근거 출처 요약

조건:
- 한국어로 답변
- 반드시 반도체 전문가처럼 기술적 의미를 설명
- HBM4E를 단순한 메모리 제품이 아니라 AI 메모리 계층, 적층/패키징, 고객 채택 타이밍 관점에서 해석
- 근거가 약한 부분은 약하다고 명시
- 증거 문서가 반복되더라도, 최종 답변에는 같은 출처/제목을 반복 나열하지 말 것"""
    return call_llm(system, user).strip(), structured_summary


def render_markdown(
    question: str,
    plain_answer: str,
    rag_answer_text: str,
    rag_summary: dict,
) -> str:
    company_impact = rag_summary.get("company_impact") or []
    evidence_quality = rag_summary.get("evidence_quality") or {}
    catalyst = rag_summary.get("catalyst_imminence") or {}
    novelty = rag_summary.get("novelty") or {}
    revenue = rag_summary.get("revenue_linkage") or {}
    normalized_event = rag_summary.get("normalized_event") or {}

    impact_lines = []
    for item in company_impact[:5]:
        impact_lines.append(
            f"- {item.get('company','')}({item.get('code','')}): "
            f"{item.get('stance','')} @ {float(item.get('confidence', 0.0)):.2f} "
            f"- {item.get('reason','')}"
        )

    evidence_lines = []
    for item in (rag_summary.get("evidence_used") or [])[:6]:
        evidence_lines.append(
            f"- `{item.get('source_type', '')}/{item.get('source', '')}`: "
            f"{item.get('title', '')} "
            f"(company={item.get('company', '') or '-'}, domain={item.get('domain', '') or '-'}, "
            f"published_at={item.get('published_at', '') or '-'}, score={float(item.get('evidence_score', 0.0) or 0.0):.3f})"
        )

    lines = [
        "# LLM vs Semiconductor Agent Comparison",
        "",
        f"- Question: {question}",
        "",
        "## LLM Only",
        plain_answer,
        "",
        "## Semiconductor Agent",
        rag_answer_text,
        "",
        "## Why The Agent Answer Should Feel More Expert",
        "- It should explain the event as a semiconductor execution milestone, not just as 'good news'.",
        f"- It should tie the event to a concrete short-horizon catalyst window: `{catalyst.get('dominant_window', 'n/a')}`.",
        f"- It should judge whether the news is truly new information: `{novelty.get('surprise_level', 'n/a')}` / `{novelty.get('market_awareness', 'n/a')}`.",
        f"- It should connect technology progress to monetization timing: `{revenue.get('link_strength', 'n/a')}` -> `{revenue.get('time_to_monetize', 'n/a')}`.",
        "",
        "## Normalized Technology Event Derived From Our Data",
        f"- Event type: `{normalized_event.get('event_type', 'n/a')}`",
        f"- Technology: `{normalized_event.get('technology', 'n/a')}`",
        f"- Event date: `{normalized_event.get('event_date', 'n/a')}`",
        f"- Company: `{normalized_event.get('related_company', 'n/a')}`",
        f"- Short-horizon hint: `{normalized_event.get('catalyst_imminence', 'n/a')}` / `{normalized_event.get('revenue_linkage', 'n/a')}` / `{normalized_event.get('market_transmission_speed', 'n/a')}`",
        "",
        "## Company-Specific Impact Derived From RAG",
        *(impact_lines or ["- none"]),
        "",
        "## Evidence Actually Used",
        f"- Evidence grade: `{evidence_quality.get('grade', 'n/a')}`",
        f"- Evidence count: `{evidence_quality.get('count', 0)}`",
        f"- Source count: `{evidence_quality.get('source_count', 0)}`",
        *(evidence_lines or ["- none"]),
        "",
        "## Structured RAG Summary",
        "```json",
        json.dumps(rag_summary, ensure_ascii=False, indent=2),
        "```",
    ]
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Compare plain LLM text answer vs RAG-backed semiconductor-agent answer.")
    parser.add_argument("question", help="Natural-language question to compare")
    parser.add_argument("--company", default="", help="Optional company hint")
    parser.add_argument("--domain", default="", help="Optional domain hint")
    parser.add_argument("--top-k", type=int, default=8, help="RAG evidence count")
    parser.add_argument("--save", default="", help="Optional markdown output path")
    args = parser.parse_args()

    plain = _plain_llm_answer(args.question)
    rag_text, rag_summary = _rag_answer(args.question, args.company, args.domain, args.top_k)

    md = render_markdown(args.question, plain, rag_text, rag_summary)
    print(md)

    if args.save:
        path = Path(args.save)
        path.write_text(md, encoding="utf-8")
        print()
        print(f"[saved] {path}")


if __name__ == "__main__":
    main()
