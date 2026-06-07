"""
macro_prompt.py
거시경제 분석 전용 프롬프트 템플릿 & LCEL 체인 빌더

노드별 사용처:
    macro_analyst_node  → build_macro_only_chain(llm)  [전담 거시 분석]
    (레거시 통합 체인)  → build_macro_chain(llm)        [macro_agent.md 기반]

입력 변수 (Human template):
    {query}          — 분석 요청 자연어
    {current_date}   — 오늘 날짜 (YYYY-MM-DD)
    {ecos_data}      — ECOS 지표 JSON 문자열 (ts_features 포맷)
    {fred_data}      — FRED / SOX 지표 JSON 문자열 (ts_features 포맷)
    {news_context}   — 뉴스 RAG 문서 포맷 문자열
    {report_context} — KCIF 리포트 RAG 문서 포맷 문자열
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

logger = logging.getLogger(__name__)

# ── 시스템 프롬프트 로딩 (레거시 통합 체인용) ──────────────────────────
_PROMPTS_DIR = Path(__file__).parent
_SYSTEM_PROMPT_PATH = _PROMPTS_DIR / "macro_agent.md"


def _load_system_prompt() -> str:
    if not _SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"시스템 프롬프트 파일을 찾을 수 없습니다: {_SYSTEM_PROMPT_PATH}"
        )
    content = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    logger.debug("시스템 프롬프트 로드 완료 (%d자)", len(content))
    return content


# ── Human Message 템플릿 (두 체인 공용) ──────────────────────────────
#
# ts_features 포맷 가이드 — 각 지표 entry에 포함될 수 있는 키:
#   current_value   : 최신 수치
#   ma_30           : 30일 이동평균  (일봉: ~22거래일, 월봉: ~1개월)
#   ma_90           : 90일 이동평균  (일봉: ~65거래일, 월봉: ~3개월)
#   mom_change_pct  : 전월 대비 변동률 (%)
#   yoy_change_pct  : 전년 동기 대비 변동률 (%)
#   volatility_3m   : 최근 3개월 표준편차 (변동성)
#   trend_label     : "상승 (MA90↑)" 형태의 파생 추세 레이블
#   historical_pct  : 36개월 이력 내 현재값 백분위 (0~100)
#
_HUMAN_TEMPLATE = """\
현재 날짜: {current_date}

══════════════════════════════════════════════════════
## [섹션 A] 정량 데이터 — TimescaleDB 시계열 피처
══════════════════════════════════════════════════════
각 지표 entry에는 다음 필드가 포함됩니다.
  · current_value / ma_30 / ma_90        : MA 스프레드 분석용 (강한 상승: current > ma_30 > ma_90)
  · mom_change_pct / yoy_change_pct      : 단기/구조적 모멘텀 판별용
  · volatility_3m                        : 변동성 — 높을수록 불확실성 리스크
  · trend_label                          : 파생 추세 레이블 참고용
  · historical_pct                       : 36개월 백분위 — 90↑ 이면 역대 고점권

### A-1. ECOS 한국은행 지표 (원/달러 환율 · 전자부품 출하지수 · 재고지수)
```json
{ecos_data}
```

### A-2. FRED / yfinance 미국 지표 (연방기금금리 · 산업생산지수 · SOX 반도체지수)
```json
{fred_data}
```

══════════════════════════════════════════════════════
## [섹션 B] 정성 데이터 — 최신 뉴스 (Google News RSS + Firecrawl)
══════════════════════════════════════════════════════
시장 심리·정책 발표·기업 가이던스 파악에 활용하십시오.
관련성 점수(relevance_score)가 낮은 기사는 보조 참고로만 사용하십시오.

{news_context}

══════════════════════════════════════════════════════
## [섹션 C] 전문가 분석 — 국제금융센터(KCIF) 리포트
══════════════════════════════════════════════════════
KCIF 보고서는 높은 신뢰도를 부여하십시오.
뉴스와 시각이 상충할 경우 confidence_score를 하향 조정하고 이를 명시하십시오.

{report_context}

══════════════════════════════════════════════════════
## [섹션 D] 분석 요청
══════════════════════════════════════════════════════

{query}

──────────────────────────────────────────────────────
위 A·B·C 세 섹션을 통합하여 시스템 프롬프트의 JSON 스키마에 정확히 맞게 응답하시오.
응답은 반드시 유효한 JSON 단일 오브젝트로만 구성되어야 합니다.
"""

# ── 거시경제 전담 시스템 프롬프트 ──────────────────────────────────────
#
# 주의: 이 문자열은 build_macro_only_chain() 에서
#       .replace("{", "{{").replace("}", "}}")  로 이스케이프 처리됩니다.
#       따라서 { } 를 그대로 써도 됩니다.
#
_MACRO_ONLY_SYSTEM_PROMPT = """\
# SYSTEM — Macro Analyst Node (거시경제 정량 분석 전담)

## 역할과 분석 범위

당신은 반도체 도메인 멀티에이전트 시스템의 **거시경제 분석 전담 노드**입니다.
지정학 분석은 별도 노드(geo_analyst)가 담당하므로, 이 노드에서는:
  - TimescaleDB 시계열 피처(MA·MoM·YoY·변동성)를 활용한 **정량 분석**
  - 한국 반도체 기업이 직면한 **거시경제 국면 판별** (BOOM/SLOWDOWN/RECESSION/RECOVERY)
  - 환율·금리·산업생산지수·반도체 출하·재고 지수의 **인과 연계 분석**

에만 집중하십시오. 지정학 이벤트(제재, 수출통제 등)는 언급하지 마십시오.

---

## [필수 프레임워크 1] 이동평균 스프레드 해석 체계

입력 데이터의 각 지표 entry에는 `current_value`, `ma_30`, `ma_90`이 제공됩니다.
**반드시** 아래 판별 기준을 적용하여 각 지표의 추세를 해석하십시오.

| 조건                                           | 추세 판정           | 신뢰도           |
|------------------------------------------------|---------------------|------------------|
| current > ma_30 > ma_90                        | 강한 상승 추세      | 高 (정배열)       |
| current > ma_90, ma_30 < ma_90                 | 단기 반등 — 주의    | 中 (골든크로스 전)|
| |ma_30 - ma_90| / ma_90 < 0.5%                 | 방향 전환 임박      | 低 (관찰 구간)    |
| current < ma_90, ma_30 > ma_90                 | 단기 조정 — 관찰    | 中 (데드크로스 전)|
| current < ma_30 < ma_90                        | 강한 하락 추세      | 高 (역배열)       |

**수치 인용 규칙 (위반 시 분석 무효)**
  올바름: "ecos.usd_krw: ma_30(1375.2) > ma_90(1368.5), 스프레드 +0.49% → 단기 강달러 지속"
  틀림:   "달러 강세 추세가 지속되고 있다"

---

## [필수 프레임워크 2] YoY·MoM 해석 원칙

| 패턴               | 해석                         | 보고 지침                               |
|--------------------|------------------------------|----------------------------------------|
| YoY < 0 & MoM > 0  | 기저효과 반등 (구조 회복 ×)  | "반등" 표현 사용, "회복" 표현 금지       |
| YoY > 0 & MoM < 0  | 성장 둔화 시작               | risk_items에 "추세 전환 경고"로 명시     |
| YoY > 0 & MoM > 0  | 모멘텀 강화 (추세 확인)      | BOOM 또는 RECOVERY 위상 검토            |
| YoY < 0 & MoM < 0  | 침체 심화                    | RECESSION 위상 확정 근거로 사용          |
| volatility_3m 高   | 방향보다 불확실성이 리스크   | confidence_score 하향 조정 + 명시       |

historical_pct 활용 기준:
  - 90 이상: 역대 고점권 → 평균 회귀 리스크 경고
  - 10 이하: 역대 저점권 → 반등 가능성 또는 구조 훼손 판단
  - 40~60:   중립 구간 → 방향성은 MA 스프레드로 판단

---

## [필수 프레임워크 3] 반도체 경기 위상 판별 기준

아래 조건 중 **3개 중 2개 이상** 충족 시 해당 위상으로 확정하십시오.

| phase      | 조건 ①                       | 조건 ②                         | 조건 ③                          |
|------------|------------------------------|--------------------------------|----------------------------------|
| BOOM       | 출하지수 YoY > +5%           | 재고지수 YoY < 0%              | SOX: current > ma_30 > ma_90    |
| SLOWDOWN   | 출하지수 YoY 0~+5% 또는 MoM 연속 둔화 | 재고지수 YoY 양전환 | 환율 volatility_3m 상승          |
| RECESSION  | 출하지수 YoY < 0%            | 재고지수 YoY > +10%            | SOX: current < ma_30 < ma_90    |
| RECOVERY   | 출하지수 MoM > +2% (2개월)   | 재고지수 YoY 감소 전환         | SOX ma_30, ma_90 골든크로스 진행 |

판별 불가 시: 가장 근접한 위상을 선택하고, phase_reasoning에 불확실 근거와
충족/미충족 조건을 명시하십시오.

---

## [필수] reasoning_flow 화살표 포맷 — 이탈 시 출력 무효

reasoning_flow는 **반드시** 아래 4단계 화살표 포맷만 사용하십시오:

  원인: [수치 포함 핵심 트리거] → 1차 영향: [즉각 파급 경로 + 관련 지표명과 수치] → 2차 영향: [연쇄 효과] → 최종 반도체 영향: [한국 반도체 기업 리스크 수치화]

규칙:
  · 화살표(→)는 정확히 3개 사용 (4단계 고정)
  · 각 단계에 지표명과 수치를 반드시 포함
  · "~할 수 있다", "~우려된다" 같은 가능성 표현 금지 — 확정형으로 기술
  · 최종 반도체 영향: 영향 기업명 또는 세그먼트 + 수치(%, %p, 억원 등) 포함

예시:
  원인: fed_funds_rate 5.33%(historical_pct=89, 역대 고점권) 장기 고착, ma_30(5.33%) ≈ ma_90(5.31%) 방향 전환 임박 →
  1차 영향: USD/KRW ma_30(1375.2) > ma_90(1368.5), 스프레드 +0.49% 강달러 지속 →
  2차 영향: ecos.electronics_shipment_index YoY -4.2%(역배열 하락 추세), 재고지수 YoY +12.3% 재고 누적 →
  최종 반도체 영향: 메모리 출하 둔화 + 재고 과잉으로 DRAM·NAND ASP 5~8% 하락 압력, 삼성·하이닉스 영업이익률 2~3%p 훼손 추정

---

## 절대 출력 규칙

유효한 JSON 단일 오브젝트만 출력하라. 마크다운 펜스(```json), 설명 문구, 앞뒤 텍스트 일절 금지.
응답은 반드시 `{` 로 시작하고 `}` 로 끝나야 한다.

---

## 출력 JSON 스키마 (이 형식만 허용)

{
  "schema_version": "1.0",
  "is_my_domain": <boolean>,
  "domain_rejection_reason": <string | null>,
  "query": <string>,
  "analysis_timestamp": <ISO8601>,

  "reasoning_flow": <"원인: [...] → 1차 영향: [...] → 2차 영향: [...] → 최종 반도체 영향: [...]">,

  "macro_analysis": {
    "phase": <"BOOM" | "SLOWDOWN" | "RECESSION" | "RECOVERY">,
    "phase_reasoning": <string — 판별에 사용한 MA 스프레드·YoY·백분위 수치를 인용, 2~3문장>,
    "risk_items": [
      {
        "factor": <string — 지표명 또는 거시 요인>,
        "current_state": <string — ma_30·ma_90·MoM·YoY·백분위를 수치 포함하여 기술>,
        "trend": <"상승" | "하락" | "보합" | "불확실">,
        "risk_direction": <"UPSIDE" | "DOWNSIDE" | "NEUTRAL">,
        "impact_horizon": <"SHORT" | "MID" | "LONG">,
        "semiconductor_linkage": <string — 반도체 사이클·한국 기업 영향 연결>
      }
    ],
    "key_data_points": <object — 핵심 지표명: 값 요약>
  },

  "overall_risk_level": <"LOW" | "MEDIUM" | "HIGH" | "CRITICAL">,
  "key_signals": [<string — 수치 포함, 최대 5개>],
  "summary": <string — 60~100자 단일 문장, phase(BOOM/SLOWDOWN/RECESSION/RECOVERY)와 핵심 리스크 반드시 포함>,
  "confidence_score": <float 0.0–1.0>,
  "data_sources": [<string>]
}

---

## 도메인 필터

is_my_domain: false 조건: 칩 수준 엔지니어링·공정 세부사항, 개별 기업 내부 미공개 정보, 비반도체 주제.
false 시: macro_analysis: null, overall_risk_level: null, confidence_score: 0.0.
데이터 없는 항목: 추정치 없이 "데이터 없음"으로 명시하라.
"""


# ── 프롬프트 빌더 ──────────────────────────────────────────────────────

def build_macro_prompt() -> ChatPromptTemplate:
    """
    레거시 통합 체인용 — macro_agent.md + Human 템플릿 조합.
    직접 호출보다는 build_macro_chain()을 통해 사용합니다.
    """
    system_prompt = _load_system_prompt()
    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", _HUMAN_TEMPLATE),
    ])


def build_macro_only_chain(llm: BaseChatModel) -> Runnable:
    """
    거시경제 분석 전용 체인 (macro_analyst_node에서 사용).

    _MACRO_ONLY_SYSTEM_PROMPT에서 { } 를 {{ }} 로 이스케이프 처리한 뒤
    ChatPromptTemplate에 주입합니다.

    Args:
        llm: 초기화된 LangChain ChatModel (gpt-4o temperature=0 권장)

    Returns:
        prompt | llm | JsonOutputParser 체인
    """
    escaped_system = _MACRO_ONLY_SYSTEM_PROMPT.replace("{", "{{").replace("}", "}}")
    prompt = ChatPromptTemplate.from_messages([
        ("system", escaped_system),
        ("human",  _HUMAN_TEMPLATE),
    ])
    return prompt | llm | JsonOutputParser()


def build_macro_chain(llm: BaseChatModel) -> Runnable:
    """
    레거시 통합 체인 (macro_agent.md 기반, 지정학 포함 종합 분석).

    Args:
        llm: 초기화된 LangChain ChatModel

    Returns:
        prompt | llm | JsonOutputParser 체인
    """
    prompt = build_macro_prompt()
    return prompt | llm | JsonOutputParser()


# ── 입력 포맷 헬퍼 ────────────────────────────────────────────────────

def format_tool_data(data: Any, max_chars: int = 8000) -> str:
    """
    Tool 실행 결과(dict/list)를 LLM 주입용 JSON 문자열로 변환합니다.
    max_chars 초과 시 잘라냅니다.
    """
    try:
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError) as exc:
        logger.warning("Tool 데이터 직렬화 실패, 문자열 변환 시도: %s", exc)
        serialized = str(data)

    if len(serialized) <= max_chars:
        return serialized

    truncated = serialized[:max_chars]
    last_nl   = truncated.rfind("\n")
    if last_nl > max_chars * 0.8:
        truncated = truncated[:last_nl]

    logger.info("Tool 데이터 잘림: %d → %d자", len(serialized), len(truncated))
    return truncated + '\n  "...": "[데이터 잘림 — 토큰 한도 초과]"\n}'


def build_chain_input(
    query:          str,
    ecos_result:    dict | None = None,
    fred_result:    dict | None = None,
    news_context:   str  | None = None,
    report_context: str  | None = None,
    current_date:   str  | None = None,
) -> dict[str, str]:
    """
    macro_analyst_node → chain.invoke()에 전달할 입력 딕셔너리를 빌드합니다.

    Args:
        query          : 분석 요청 문자열
        ecos_result    : ECOS 지표 ts_features 포맷 dict (None이면 빈 객체)
        fred_result    : FRED / SOX 지표 ts_features 포맷 dict
        news_context   : 뉴스 RAG 문서 포맷 문자열
        report_context : KCIF 리포트 RAG 문서 포맷 문자열
        current_date   : 날짜 문자열 (None이면 오늘 날짜 자동 삽입)

    Returns:
        chain.invoke()에 전달할 dict
    """
    from datetime import date

    return {
        "query":          query,
        "current_date":   current_date or date.today().isoformat(),
        "ecos_data":      format_tool_data(ecos_result    or {"status": "데이터 없음"}),
        "fred_data":      format_tool_data(fred_result    or {"status": "데이터 없음"}),
        "news_context":   news_context   or "관련 뉴스 없음",
        "report_context": report_context or "관련 리포트 없음",
    }
