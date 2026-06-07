"""
LLM 단독 vs MacroAnalysisAgent 응답 비교 스크립트

같은 질문을 gpt-4o 단독(RAG·DB 없음)과 에이전트(RAG + TimescaleDB + 전문 프롬프트)에
동시에 던져 응답 품질을 비교합니다.

사용법:
    python scripts/compare.py "미중 반도체 수출 규제 영향은?"
    python scripts/compare.py  # 기본 질문 사용
"""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from langchain_openai import ChatOpenAI
from macro_agent.agent import MacroAnalysisAgent

_DIVIDER = "─" * 72
_WIDTH   = 72


def _wrap(text: str, indent: int = 0) -> str:
    prefix = " " * indent
    return textwrap.fill(str(text), width=_WIDTH, initial_indent=prefix,
                         subsequent_indent=prefix)


# ── 1. Plain gpt-4o ──────────────────────────────────────────────────────

def call_plain_llm(question: str) -> tuple[str, float]:
    """RAG·DB 없이 gpt-4o에 직접 질문합니다."""
    llm = ChatOpenAI(model="gpt-4o", temperature=0, max_tokens=2000)
    t0 = time.time()
    response = llm.invoke(question)
    elapsed = time.time() - t0
    return response.content, elapsed


# ── 2. MacroAnalysisAgent ─────────────────────────────────────────────────

def call_agent(question: str) -> tuple[dict, float]:
    """MacroAnalysisAgent(RAG + TimescaleDB + 전문 프롬프트)로 분석합니다."""
    agent = MacroAnalysisAgent(auto_init_db=False)
    t0 = time.time()
    result = agent.invoke(question)
    elapsed = time.time() - t0
    return result, elapsed


# ── 출력 포맷터 ───────────────────────────────────────────────────────────

def print_plain(answer: str, elapsed: float) -> None:
    print(f"\n{'━'*_WIDTH}")
    print(f"  [A] gpt-4o 단독  (RAG·DB 없음)   ⏱  {elapsed:.1f}s")
    print(f"{'━'*_WIDTH}\n")
    for line in answer.split("\n"):
        print(_wrap(line) if line.strip() else "")


def print_agent(result: dict, elapsed: float) -> None:
    print(f"\n{'━'*_WIDTH}")
    print(f"  [B] MacroAnalysisAgent            ⏱  {elapsed:.1f}s")
    print(f"{'━'*_WIDTH}\n")

    if not result.get("is_my_domain"):
        print(f"  ⚠  도메인 외 질문: {result.get('domain_rejection_reason')}")
        return

    # 핵심 필드만 보기 좋게 출력
    fields = [
        ("overall_risk_level", "종합 리스크"),
        ("summary",            "요약"),
        ("confidence_score",   "신뢰도"),
    ]
    for key, label in fields:
        val = result.get(key)
        if val is not None:
            print(f"  [{label}]")
            print(_wrap(str(val), indent=4))
            print()

    signals = result.get("key_signals") or []
    if signals:
        print("  [핵심 시그널]")
        for s in signals[:5]:
            print(_wrap(f"• {s}", indent=4))
        print()

    # 거시 분석 — risk_items 중 DOWNSIDE 우선 최대 3개
    macro = result.get("macro_analysis") or {}
    risk_items = macro.get("risk_items") or []
    if risk_items:
        print("  [거시 분석 — 주요 리스크 팩터]")
        sorted_items = sorted(
            risk_items,
            key=lambda x: x.get("risk_direction", "") == "DOWNSIDE",
            reverse=True,
        )
        for item in sorted_items[:3]:
            factor = item.get("factor", "")
            state  = item.get("current_state", "")
            dirn   = item.get("risk_direction", "")
            print(_wrap(f"• [{dirn}] {factor}: {state}", indent=4))
        print()

    # 지정학 분석 — geo_risk_summary + risk_items 상위 2개
    geo = result.get("geo_analysis") or {}
    geo_summary = geo.get("geo_risk_summary", "")
    geo_risk_events = geo.get("risk_items") or []
    if geo_summary or geo_risk_events:
        print("  [지정학 분석]")
        if geo_summary:
            print(_wrap(geo_summary[:400], indent=4))
        if geo_risk_events:
            print()
            print(_wrap(f"  주요 이벤트 ({len(geo_risk_events)}건 중 상위 2건):", indent=4))
            for e in geo_risk_events[:2]:
                region = e.get("region", "")
                event  = e.get("event", "")
                level  = e.get("risk_level", "")
                print(_wrap(f"• [{level}] {region} — {event}", indent=4))
        print()

    # 데이터 소스
    sources = result.get("data_sources") or []
    meta = result.get("_agent_meta") or {}
    rag_ctx = meta.get("rag_context") or ""
    ts_ctx  = meta.get("ts_context") or ""
    print(f"  [사용 데이터]  {rag_ctx}  /  {ts_ctx}")


# ── 비교 요약 ─────────────────────────────────────────────────────────────

def print_diff_summary(plain_ans: str, agent_result: dict) -> None:
    print(f"\n{'━'*_WIDTH}")
    print(f"  [비교 포인트]")
    print(f"{'━'*_WIDTH}")

    agent_summary = (agent_result.get("summary") or "")[:200]
    plain_preview = plain_ans[:200].replace("\n", " ")

    plain_words = set(plain_ans.lower().split())
    agent_words = set(agent_summary.lower().split())
    overlap = len(plain_words & agent_words) / max(len(plain_words | agent_words), 1)

    meta    = agent_result.get("_agent_meta") or {}
    rag_ctx = meta.get("rag_context") or ""
    ts_ctx  = meta.get("ts_context") or ""

    print(f"\n  gpt-4o 단독   : 학습 데이터만 사용, 최신 수치 없음")
    print(f"  에이전트      : {rag_ctx}  /  {ts_ctx}")
    print(f"  단어 중복률   : {overlap:.0%}  (낮을수록 에이전트가 독자적 정보 활용)")
    print(f"  에이전트 신뢰도: {agent_result.get('confidence_score', 0):.0%}\n")


# ── 메인 ─────────────────────────────────────────────────────────────────

def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 \
        else "현재 미중 반도체 수출 규제가 한국 반도체 업황에 미치는 영향을 분석해줘."

    print(f"\n{_DIVIDER}")
    print(f"  질문: {question}")
    print(f"{_DIVIDER}")

    # 두 응답을 순차 실행
    print("\n  ▶ [A] gpt-4o 단독 호출 중...", flush=True)
    plain_ans, plain_time = call_plain_llm(question)

    print("  ▶ [B] MacroAnalysisAgent 실행 중...", flush=True)
    agent_result, agent_time = call_agent(question)

    # 출력
    print_plain(plain_ans, plain_time)
    print_agent(agent_result, agent_time)
    print_diff_summary(plain_ans, agent_result)


if __name__ == "__main__":
    main()
