"""
final_report.py — 최종 출력 에이전트 인터페이스

외부 오케스트레이터(최종 출력 에이전트)는 이 모듈만 import하여
MacroAnalysisAgent 전체를 호출하고 구조화된 JSON 분석 결과를 받습니다.

Usage (Python 모듈로 사용):
    from final_report import generate_report

    result: dict = generate_report("미국 수출통제가 반도체 공급망에 미치는 영향은?")
    if result["is_my_domain"]:
        print(result["summary"])

Usage (CLI):
    python final_report.py "미-중 무역분쟁 리스크를 분석해줘"
    python final_report.py "..." --sender orchestrator --pretty

출력 JSON 스키마:
    schema_version        str        "1.0"
    is_my_domain          bool       반도체 도메인 질문 여부
    domain_rejection_reason str|null 도메인 외 질문 시 거부 사유
    query                 str        원본 질문
    analysis_timestamp    str        ISO8601 분석 시각
    reasoning_flow        str|null   LLM 추론 흐름 요약
    macro_analysis        dict|null  거시경제 정량 분석 결과
    geo_analysis          dict|null  지정학 리스크 분석 결과
    overall_risk_level    str|null   "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
    key_signals           list[str]  핵심 시그널 목록
    summary               str|null   자연어 최종 요약
    confidence_score      float      0.0 ~ 1.0
    data_sources          list[str]  사용된 데이터 소스 목록
    _parse_error          bool       LLM 파싱 실패 여부
    _agent_meta           dict       에이전트 실행 메타데이터
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

# ── 환경변수 로드 (.env 우선) ─────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
except ImportError:
    pass  # dotenv 없으면 시스템 환경변수만 사용

# ── 로깅 설정 ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("final_report")

# ── MacroAnalysisAgent import (src 경로 자동 추가) ────────────────────
_src_path = os.path.join(os.path.dirname(__file__), "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

from macro_agent.agent import MacroAnalysisAgent  # noqa: E402


# ── 에이전트 싱글톤 (모듈 로드 시 1회 초기화) ─────────────────────────
_agent: MacroAnalysisAgent | None = None


def _get_agent() -> MacroAnalysisAgent:
    global _agent
    if _agent is None:
        logger.info("MacroAnalysisAgent 초기화 중...")
        _agent = MacroAnalysisAgent(auto_init_db=False)
        logger.info("MacroAnalysisAgent 초기화 완료")
    return _agent


# ── 공개 API ──────────────────────────────────────────────────────────

def generate_report(
    question: str,
    sender: str = "orchestrator",
) -> dict[str, Any]:
    """
    거시경제·지정학 리스크 분석을 수행하고 구조화된 JSON dict를 반환합니다.

    최종 출력 에이전트(오케스트레이터)가 호출하는 주 진입점입니다.

    Args:
        question: 분석 요청 자연어 질문 (반도체 도메인)
        sender:   호출자 식별자 (로깅·추적용)

    Returns:
        분석 결과 dict — 항상 dict를 반환하며 예외를 전파하지 않습니다.
        오류 발생 시 _parse_error=True와 함께 에러 스키마를 반환합니다.

    Examples:
        >>> result = generate_report("미-중 수출통제가 반도체 공급망에 미치는 영향은?")
        >>> print(result["overall_risk_level"])  # "HIGH"
        >>> print(result["summary"])
    """
    if not question or not question.strip():
        return {
            "schema_version": "1.0",
            "is_my_domain": False,
            "domain_rejection_reason": "질문이 비어있습니다.",
            "query": question,
            "macro_analysis": None,
            "geo_analysis": None,
            "overall_risk_level": None,
            "key_signals": [],
            "summary": None,
            "confidence_score": 0.0,
            "data_sources": [],
            "_parse_error": False,
            "_agent_meta": {"fatal_error": "empty_question"},
        }

    logger.info("[generate_report] 질문 수신 — sender=%s, question=%s", sender, question[:80])

    agent = _get_agent()
    result = agent.invoke(question, sender=sender)

    logger.info(
        "[generate_report] 분석 완료 — is_my_domain=%s, risk=%s, confidence=%.2f",
        result.get("is_my_domain"),
        result.get("overall_risk_level"),
        result.get("confidence_score", 0.0),
    )

    return result


async def agenerate_report(
    question: str,
    sender: str = "orchestrator",
) -> dict[str, Any]:
    """
    generate_report()의 비동기 버전.
    FastAPI, async 오케스트레이터 등 async 환경에서 사용합니다.
    """
    if not question or not question.strip():
        return {
            "schema_version": "1.0",
            "is_my_domain": False,
            "domain_rejection_reason": "질문이 비어있습니다.",
            "query": question,
            "macro_analysis": None,
            "geo_analysis": None,
            "overall_risk_level": None,
            "key_signals": [],
            "summary": None,
            "confidence_score": 0.0,
            "data_sources": [],
            "_parse_error": False,
            "_agent_meta": {"fatal_error": "empty_question"},
        }

    logger.info("[agenerate_report] 질문 수신 — sender=%s", sender)

    agent = _get_agent()
    result = await agent.ainvoke(question, sender=sender)

    logger.info(
        "[agenerate_report] 분석 완료 — risk=%s, confidence=%.2f",
        result.get("overall_risk_level"),
        result.get("confidence_score", 0.0),
    )

    return result


# ── CLI 진입점 ────────────────────────────────────────────────────────

def _parse_args() -> tuple[str, str, bool]:
    """간단한 CLI 인수 파서 (argparse 불필요 수준)"""
    import argparse
    parser = argparse.ArgumentParser(
        description="MacroAnalysisAgent CLI — 반도체 거시경제·지정학 리스크 분석",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python final_report.py "미-중 수출통제 리스크를 분석해줘"
  python final_report.py "반도체 업황 전망" --sender orchestrator --pretty
        """,
    )
    parser.add_argument("question", help="분석 요청 자연어 질문")
    parser.add_argument(
        "--sender", default="cli", help="호출자 식별자 (기본값: cli)"
    )
    parser.add_argument(
        "--pretty", action="store_true", help="JSON 출력을 들여쓰기 형식으로 표시"
    )
    args = parser.parse_args()
    return args.question, args.sender, args.pretty


if __name__ == "__main__":
    question, sender, pretty = _parse_args()

    print(f"\n분석 시작: {question!r}\n{'=' * 60}", file=sys.stderr)

    result = generate_report(question, sender=sender)

    indent = 2 if pretty else None
    output = json.dumps(result, ensure_ascii=False, indent=indent, default=str)
    print(output)

    # 도메인 외 질문이거나 치명적 오류 시 비정상 종료 코드 반환
    if not result.get("is_my_domain") or result.get("_parse_error"):
        sys.exit(1)
