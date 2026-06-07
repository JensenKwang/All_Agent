"""
AutoGen 기반 반도체 주가 예측 멀티에이전트 시스템

4개 전문 에이전트(Search, Economy, Market, Semiconductor)를
AutoGen GroupChat으로 통합하여 대화형 주가 예측을 수행합니다.

사용법:
    python main.py
    python main.py "삼성전자 주가 전망을 분석해줘"

환경변수:
    OPENAI_API_KEY  : OpenAI API 키 (필수)
    NAVER_CLIENT_ID : 네이버 API ID (search_agent용, 선택)
    NAVER_CLIENT_SECRET : 네이버 API Secret (선택)
    DART_API_KEY    : DART 공시 API 키 (선택)

구조:
    User ↔ GroupChatManager
            ├── SearchExpert     (뉴스/공시/SNS 수집)
            ├── EconomyExpert    (거시경제/지정학 리스크)
            ├── MarketExpert     (기술적 분석/수급/타이밍)
            ├── SemiExpert       (반도체 기술 이벤트)
            └── Integrator       (종합 판단 → 주가 전망)
"""

import os
import sys
import json
from typing import Annotated
from pathlib import Path

# ── 경로 설정 ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "economy_agent", "src"))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, "semiconductor_agent_design"))

# ── 통합 .env 로딩 (각 에이전트 import 전에 먼저 로드) ──
from dotenv import load_dotenv

_env_file = Path(BASE_DIR) / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=True)
    print(f"[ENV] 통합 .env 로드 완료: {_env_file}")
else:
    print(f"[WARN] .env 파일 없음: {_env_file}")
    print("       .env.example을 .env로 복사하고 키를 설정하세요.")

from autogen import ConversableAgent, GroupChat, GroupChatManager, register_function


# ═══════════════════════════════════════════════════════════════
# LLM 설정
# ═══════════════════════════════════════════════════════════════

def _load_api_key() -> str:
    """OPENAI_API_KEY를 .env → 환경변수 → OpenAI_key.txt 순으로 탐색."""
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    # .env에 없으면 레거시 키 파일 시도
    key_file = os.path.join(BASE_DIR, "OpenAI_key.txt")
    if os.path.exists(key_file):
        raw = open(key_file, "r", encoding="utf-8").read().strip()
        if "=" in raw and "OPENAI_API_KEY" in raw:
            raw = raw.split("=", 1)[1].strip()
        key = raw.strip('"').strip("'")
        os.environ["OPENAI_API_KEY"] = key  # 다른 에이전트에서도 사용 가능하도록
        return key
    raise ValueError(
        "OPENAI_API_KEY를 찾을 수 없습니다.\n"
        "  1) .env 파일에 OPENAI_API_KEY=sk-... 추가, 또는\n"
        "  2) 환경변수 설정: export OPENAI_API_KEY=sk-..., 또는\n"
        "  3) 프로젝트 루트에 OpenAI_key.txt 생성"
    )


API_KEY = _load_api_key()

llm_config = {
    "config_list": [{"model": "gpt-4o-mini", "api_key": API_KEY}],
    "temperature": 0.1,
}


# ═══════════════════════════════════════════════════════════════
# 도구 함수 — 각 에이전트의 핵심 기능 래핑
# ═══════════════════════════════════════════════════════════════

def search_news_and_disclosures(
    query: Annotated[str, "검색 키워드 (예: '삼성전자', 'HBM', 'SK하이닉스')"],
    news_count: Annotated[int, "수집할 뉴스 수 (기본 10)"] = 10,
) -> str:
    """Search Agent: 뉴스, 공시, SNS 데이터를 수집하고 신뢰도를 평가합니다."""
    try:
        from search_agent.search_agent import run as search_run

        result = search_run(query, news_count=news_count)
        return json.dumps(
            {
                "agent": "Search Agent",
                "keyword": result.get("keyword"),
                "news_count": result.get("news_count"),
                "disclosure_count": result.get("disclosure_count"),
                "threads_count": result.get("threads_count"),
                "key_evidence": result.get("key_evidence", [])[:15],
                "limitations": result.get("limitations", []),
                "handoff_message": result.get("handoff_message"),
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return json.dumps({"agent": "Search Agent", "error": str(e)}, ensure_ascii=False)


def analyze_macro_economy(
    question: Annotated[str, "거시경제/지정학 분석 질문 (한국어)"],
) -> str:
    """Economy Agent: 거시경제 및 지정학 리스크를 분석합니다. (금리, 환율, PMI, 수출통제 등)"""
    try:
        from macro_agent.agent import MacroAnalysisAgent

        agent = MacroAnalysisAgent(auto_init_db=False)
        result = agent.invoke(question)
        return json.dumps(
            {
                "agent": "Economy Agent",
                "is_my_domain": result.get("is_my_domain"),
                "overall_risk_level": result.get("overall_risk_level"),
                "key_signals": result.get("key_signals", []),
                "summary": result.get("summary"),
                "confidence_score": result.get("confidence_score"),
                "reasoning_flow": result.get("reasoning_flow"),
                "data_sources": result.get("data_sources", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return json.dumps({"agent": "Economy Agent", "error": str(e)}, ensure_ascii=False)


def analyze_market_technicals(
    collect_data: Annotated[bool, "True=최신 데이터 수집 후 분석, False=기존 캐시 데이터 사용"] = False,
) -> str:
    """Market Agent: 시장 기술적 분석 (추세, 모멘텀, 수급, 상대강도, 리스크, Timing Readiness)을 수행합니다."""
    try:
        from market_agent.market_agent import MarketAgent as MA

        agent = MA(use_gpt=False)
        result = agent.run(collect_data=collect_data, max_pages=50)
        reports = []
        for r in result["report"]["json"].get("reports", []):
            reports.append(
                {
                    "asset": r["target"]["asset_name"],
                    "code": r["target"]["asset_code"],
                    "stance": r["stance"],
                    "confidence": r["confidence"],
                    "timing_score": r["timing_readiness"]["score"],
                    "timing_zone": r["timing_readiness"]["zone"],
                    "trend": r["technical_view"]["view"],
                    "momentum": r["momentum_view"]["view"],
                    "flow": r["flow_view"]["view"],
                    "relative_strength": r.get("relative_strength_view", {}).get("view", "N/A"),
                    "risk": r["risk_view"]["view"],
                    "rationale": r["rationale"],
                }
            )
        return json.dumps(
            {"agent": "Market Agent", "assets_analyzed": len(reports), "reports": reports},
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return json.dumps({"agent": "Market Agent", "error": str(e)}, ensure_ascii=False)


def analyze_semiconductor_tech(
    query: Annotated[str, "반도체 기술 이벤트 검색어 (예: 'HBM4', 'Samsung EUV', 'CoWoS')"],
) -> str:
    """Semiconductor Agent: 반도체 기술 이벤트를 분석하고 주가 영향(기댓값, 시장 반영)을 평가합니다."""
    try:
        from app.agent.pipeline import run_from_rag

        report = run_from_rag(query, verbose=False)
        return json.dumps(
            {
                "agent": "Semiconductor Agent",
                "headline": report.headline,
                "ev_score": report.ev.ev_score,
                "market_signal": report.market.signal,
                "innovation_score": getattr(report.evaluation, "innovation_score", None),
                "full_report": report.full_report[:3000],
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        return json.dumps({"agent": "Semiconductor Agent", "error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# AutoGen 에이전트 정의
# ═══════════════════════════════════════════════════════════════

user_proxy = ConversableAgent(
    name="User",
    human_input_mode="ALWAYS",
    is_termination_msg=lambda x: "TERMINATE" in (x.get("content", "") or ""),
    code_execution_config=False,
    llm_config=False,
    system_message="사용자. 주가 예측 관련 질문을 합니다.",
)

search_expert = ConversableAgent(
    name="SearchExpert",
    system_message=(
        "당신은 반도체 뉴스/공시/SNS 데이터 수집 전문가입니다.\n"
        "search_news_and_disclosures 도구를 호출하여 관련 데이터를 수집하세요.\n"
        "수집한 결과의 핵심 뉴스와 공시를 간결하게 요약 보고하세요.\n"
        "보고 범위: 뉴스 헤드라인, 공시 제목, SNS 동향만 다룹니다.\n"
        "거시경제, 기술적 분석, 반도체 기술은 다른 전문가에게 맡기세요."
    ),
    llm_config=llm_config,
)

economy_expert = ConversableAgent(
    name="EconomyExpert",
    system_message=(
        "당신은 거시경제/지정학 리스크 분석 전문가입니다.\n"
        "analyze_macro_economy 도구를 호출하여 반도체 산업에 영향을 미치는\n"
        "거시경제 환경을 분석하세요.\n"
        "분석 범위: 금리, 환율, 무역정책, 지정학적 리스크, PMI, 수출 동향.\n"
        "분석 결과의 핵심 리스크 레벨과 시그널을 보고하세요.\n"
        "뉴스 수집, 기술적 분석, 반도체 기술은 다른 전문가에게 맡기세요."
    ),
    llm_config=llm_config,
)

market_expert = ConversableAgent(
    name="MarketExpert",
    system_message=(
        "당신은 시장 기술적 분석 전문가입니다.\n"
        "analyze_market_technicals 도구를 호출하여 주가 추세, 모멘텀,\n"
        "투자주체 수급, 상대강도, 리스크를 분석하세요.\n"
        "Timing Readiness(0-100) 점수와 진입 적합 구간을 보고하세요.\n"
        "분석 범위: 가격, 거래량, 이동평균, RSI, MACD, 외국인/기관 수급.\n"
        "뉴스, 거시경제, 반도체 기술은 다른 전문가에게 맡기세요."
    ),
    llm_config=llm_config,
)

semi_expert = ConversableAgent(
    name="SemiExpert",
    system_message=(
        "당신은 반도체 기술 분석 전문가입니다.\n"
        "analyze_semiconductor_tech 도구를 호출하여 반도체 기술 이벤트\n"
        "(HBM, EUV, CoWoS, GAA 등)의 주가 영향을 분석하세요.\n"
        "기댓값(EV score), 시장 반영 여부, 수혜/위협 기업을 보고하세요.\n"
        "뉴스 수집, 거시경제, 시장 기술적 분석은 다른 전문가에게 맡기세요."
    ),
    llm_config=llm_config,
)

integrator = ConversableAgent(
    name="Integrator",
    system_message=(
        "당신은 반도체 주가 예측 통합 분석가입니다.\n"
        "다른 전문가들(SearchExpert, EconomyExpert, MarketExpert, SemiExpert)의\n"
        "분석 결과를 종합하여 최종 주가 전망을 제시하세요.\n\n"
        "종합 보고서에 반드시 포함할 내용:\n"
        "1. 각 에이전트 핵심 판단 요약 (1~2줄씩)\n"
        "2. 에이전트 간 의견 충돌/일치 분석\n"
        "3. 종합 판단 (Bullish / Neutral / Bearish)\n"
        "4. 신뢰도 (High / Medium / Low) 및 근거\n"
        "5. 주요 리스크 요인\n"
        "6. 향후 7일 / 14일 / 30일 방향성 전망\n\n"
        "모든 전문가의 분석이 완료된 후에 종합을 시작하세요.\n"
        "종합 보고가 끝나면 응답 마지막에 반드시 TERMINATE 를 추가하세요."
    ),
    llm_config=llm_config,
)


# ═══════════════════════════════════════════════════════════════
# 도구 등록 — 각 전문가가 자신의 도구를 호출하고, User가 실행
# ═══════════════════════════════════════════════════════════════

register_function(
    search_news_and_disclosures,
    caller=search_expert,
    executor=user_proxy,
    name="search_news_and_disclosures",
    description="뉴스, 공시, SNS 데이터를 수집하고 신뢰도를 평가합니다.",
)

register_function(
    analyze_macro_economy,
    caller=economy_expert,
    executor=user_proxy,
    name="analyze_macro_economy",
    description="거시경제 및 지정학 리스크를 분석합니다.",
)

register_function(
    analyze_market_technicals,
    caller=market_expert,
    executor=user_proxy,
    name="analyze_market_technicals",
    description="시장 기술적 분석 (추세/모멘텀/수급/리스크/타이밍)을 수행합니다.",
)

register_function(
    analyze_semiconductor_tech,
    caller=semi_expert,
    executor=user_proxy,
    name="analyze_semiconductor_tech",
    description="반도체 기술 이벤트의 주가 영향을 분석합니다.",
)


# ═══════════════════════════════════════════════════════════════
# GroupChat 설정
# ═══════════════════════════════════════════════════════════════

ALLOWED_TRANSITIONS = {
    user_proxy: [search_expert, economy_expert, market_expert, semi_expert, integrator],
    search_expert: [user_proxy],
    economy_expert: [user_proxy],
    market_expert: [user_proxy],
    semi_expert: [user_proxy],
    integrator: [user_proxy],
}

group_chat = GroupChat(
    agents=[user_proxy, search_expert, economy_expert, market_expert, semi_expert, integrator],
    allowed_or_disallowed_speaker_transitions=ALLOWED_TRANSITIONS,
    speaker_transitions_type="allowed",
    messages=[],
    max_round=25,
    speaker_selection_method="auto",
    select_speaker_prompt_template=(
        "아래는 반도체 주가 예측 멀티에이전트 대화입니다.\n"
        "사용자의 질문에 답하기 위해 다음 전문가 중 한 명을 선택하세요:\n"
        "- SearchExpert: 뉴스/공시 데이터가 필요할 때\n"
        "- EconomyExpert: 거시경제/지정학 분석이 필요할 때\n"
        "- MarketExpert: 기술적 분석/수급/타이밍이 필요할 때\n"
        "- SemiExpert: 반도체 기술 이벤트 분석이 필요할 때\n"
        "- Integrator: 모든 전문가 분석이 완료된 후 종합 판단할 때\n\n"
        "일반적으로 SearchExpert → EconomyExpert → MarketExpert → SemiExpert → Integrator 순서로 진행합니다.\n"
        "도구 호출 결과가 반환되면 다음 전문가를 선택하세요.\n"
        "모든 전문가 분석이 완료되면 Integrator를 선택하세요."
    ),
)

manager = GroupChatManager(
    groupchat=group_chat,
    llm_config=llm_config,
)


# ═══════════════════════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print(" AutoGen 반도체 주가 예측 멀티에이전트 시스템")
    print("=" * 60)
    print()
    print(" 전문가 에이전트:")
    print("   - SearchExpert     : 뉴스/공시/SNS 수집")
    print("   - EconomyExpert    : 거시경제/지정학 리스크")
    print("   - MarketExpert     : 기술적 분석/수급/타이밍")
    print("   - SemiExpert       : 반도체 기술 이벤트")
    print("   - Integrator       : 종합 판단")
    print()
    print(" 예시 질문:")
    print('   "삼성전자 주가 전망을 분석해줘"')
    print('   "SK하이닉스 HBM 관련 최신 동향과 주가 영향을 알려줘"')
    print('   "반도체 섹터 전체적인 투자 환경을 평가해줘"')
    print()
    print("=" * 60)

    if len(sys.argv) > 1:
        initial_message = " ".join(sys.argv[1:])
    else:
        initial_message = input("\n분석할 내용을 입력하세요: ").strip()
        if not initial_message:
            initial_message = "삼성전자 주가 전망을 분석해줘"

    print(f"\n[시작] '{initial_message}'\n")

    user_proxy.initiate_chat(manager, message=initial_message)
