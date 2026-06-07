"""
AutoGen 기반 반도체 주가 예측 멀티에이전트 시스템

4개 전문 에이전트(Search, Economy, Market, Semiconductor)를
AutoGen SelectorGroupChat으로 통합하여 대화형 주가 예측을 수행합니다.

사용법:
    python main.py
    python main.py "삼성전자 주가 전망을 분석해줘"

환경변수:
    OPENAI_API_KEY  : OpenAI API 키 (필수)
    기타 키는 .env 파일 참조

구조:
    User → SelectorGroupChat (GPT가 다음 발화자 자동 선택)
            ├── SearchExpert     (뉴스/공시/SNS 수집)
            ├── EconomyExpert    (거시경제/지정학 리스크)
            ├── MarketExpert     (기술적 분석/수급/타이밍)
            ├── SemiExpert       (반도체 기술 이벤트)
            └── Integrator       (종합 판단 → 주가 전망)
"""

import asyncio
import os
import sys
import json
from pathlib import Path

# ── Windows 콘솔 UTF-8 인코딩 설정 (cp949 에러 방지) ──
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    print(f"[ENV] 통합 .env 로드 완료")
else:
    print(f"[WARN] .env 파일 없음 — .env.example을 .env로 복사하고 키를 설정하세요.")

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient


# ═══════════════════════════════════════════════════════════════
# LLM 클라이언트
# ═══════════════════════════════════════════════════════════════

def _load_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    key_file = os.path.join(BASE_DIR, "OpenAI_key.txt")
    if os.path.exists(key_file):
        raw = open(key_file, "r", encoding="utf-8").read().strip()
        if "=" in raw and "OPENAI_API_KEY" in raw:
            raw = raw.split("=", 1)[1].strip()
        key = raw.strip('"').strip("'")
        os.environ["OPENAI_API_KEY"] = key
        return key
    raise ValueError(
        "OPENAI_API_KEY를 찾을 수 없습니다.\n"
        "  .env 파일에 OPENAI_API_KEY=sk-... 추가하세요."
    )


API_KEY = _load_api_key()

model_client = OpenAIChatCompletionClient(
    model="gpt-4o-mini",
    api_key=API_KEY,
)


# ═══════════════════════════════════════════════════════════════
# 도구 함수 — 각 에이전트의 핵심 기능 래핑
# ═══════════════════════════════════════════════════════════════

def search_news_and_disclosures(query: str, news_count: int = 10) -> str:
    """뉴스, 공시, SNS 데이터를 수집하고 신뢰도를 평가합니다.

    Args:
        query: 검색 키워드 (예: '삼성전자', 'HBM', 'SK하이닉스')
        news_count: 수집할 뉴스 수 (기본 10)
    """
    try:
        # search_agent 내부 모듈(naver_news_api 등)이 같은 폴더 import 필요
        _sa_dir = os.path.join(BASE_DIR, "search_agent")
        if _sa_dir not in sys.path:
            sys.path.insert(0, _sa_dir)
        import importlib.util
        _spec = importlib.util.spec_from_file_location(
            "search_agent_mod", os.path.join(_sa_dir, "search_agent.py")
        )
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        search_run = _mod.run

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


def analyze_macro_economy(question: str) -> str:
    """거시경제 및 지정학 리스크를 분석합니다. (금리, 환율, PMI, 수출통제 등)

    Args:
        question: 거시경제/지정학 분석 질문 (한국어)
    """
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


def analyze_market_technicals(collect_data: bool = False) -> str:
    """시장 기술적 분석 (추세, 모멘텀, 수급, 상대강도, 리스크, Timing Readiness)을 수행합니다.

    Args:
        collect_data: True이면 최신 데이터 수집 후 분석, False이면 기존 캐시 데이터 사용
    """
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


def analyze_semiconductor_tech(query: str) -> str:
    """반도체 기술 이벤트를 분석하고 주가 영향(기댓값, 시장 반영)을 평가합니다.

    Args:
        query: 반도체 기술 이벤트 검색어 (예: 'HBM4', 'Samsung EUV', 'CoWoS')
    """
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

search_expert = AssistantAgent(
    name="SearchExpert",
    model_client=model_client,
    tools=[search_news_and_disclosures],
    system_message=(
        "당신은 반도체 뉴스/공시/SNS 데이터 수집 전문가입니다.\n"
        "search_news_and_disclosures 도구를 호출하여 관련 데이터를 수집하세요.\n"
        "수집한 결과의 핵심 뉴스와 공시를 간결하게 요약 보고하세요.\n"
        "보고 범위: 뉴스 헤드라인, 공시 제목, SNS 동향만 다룹니다.\n"
        "거시경제, 기술적 분석, 반도체 기술은 다른 전문가에게 맡기세요."
    ),
)

economy_expert = AssistantAgent(
    name="EconomyExpert",
    model_client=model_client,
    tools=[analyze_macro_economy],
    system_message=(
        "당신은 거시경제/지정학 리스크 분석 전문가입니다.\n"
        "반드시 analyze_macro_economy 도구를 호출하세요. 도구 호출 없이 답변하지 마세요.\n"
        "분석 범위: 금리, 환율, 무역정책, 지정학적 리스크, PMI, 수출 동향.\n"
        "도구 결과의 핵심 리스크 레벨과 시그널을 보고하세요.\n"
        "뉴스 수집, 기술적 분석, 반도체 기술은 다른 전문가에게 맡기세요."
    ),
)

market_expert = AssistantAgent(
    name="MarketExpert",
    model_client=model_client,
    tools=[analyze_market_technicals],
    system_message=(
        "당신은 시장 기술적 분석 전문가입니다.\n"
        "반드시 analyze_market_technicals 도구를 호출하세요. 도구 호출 없이 답변하지 마세요.\n"
        "Timing Readiness(0-100) 점수와 진입 적합 구간을 보고하세요.\n"
        "분석 범위: 가격, 거래량, 이동평균, RSI, MACD, 외국인/기관 수급.\n"
        "뉴스, 거시경제, 반도체 기술은 다른 전문가에게 맡기세요."
    ),
)

semi_expert = AssistantAgent(
    name="SemiExpert",
    model_client=model_client,
    tools=[analyze_semiconductor_tech],
    system_message=(
        "당신은 반도체 기술 분석 전문가입니다.\n"
        "반드시 analyze_semiconductor_tech 도구를 호출하세요. 도구 호출 없이 답변하지 마세요.\n"
        "기댓값(EV score), 시장 반영 여부, 수혜/위협 기업을 보고하세요.\n"
        "뉴스 수집, 거시경제, 시장 기술적 분석은 다른 전문가에게 맡기세요."
    ),
)

integrator = AssistantAgent(
    name="Integrator",
    model_client=model_client,
    system_message=(
        "당신은 반도체 주가 예측 통합 분석가입니다.\n"
        "다른 전문가들(SearchExpert, EconomyExpert, MarketExpert, SemiExpert)의\n"
        "분석 결과를 종합하여 최종 주가 전망을 제시하세요.\n\n"
        "중요: 4개 전문가 에이전트의 tool 호출 결과가 대화에 모두 나타난 후에만 종합 보고서를 작성하세요.\n"
        "아직 tool 호출을 하지 않은 에이전트가 있다면 '(에이전트이름)의 분석을 요청합니다'라고만 말하세요.\n\n"
        "종합 보고서에 반드시 포함할 내용:\n"
        "1. 각 에이전트 핵심 판단 요약 (1~2줄씩)\n"
        "2. 에이전트 간 의견 충돌/일치 분석\n"
        "3. 종합 판단 (Bullish / Neutral / Bearish)\n"
        "4. 신뢰도 (High / Medium / Low) 및 근거\n"
        "5. 주요 리스크 요인\n"
        "6. 향후 7일 / 14일 / 30일 방향성 전망\n\n"
        "종합 보고가 끝나면 응답 마지막에 반드시 TERMINATE 를 추가하세요."
    ),
)


# ═══════════════════════════════════════════════════════════════
# SelectorGroupChat 설정
# ═══════════════════════════════════════════════════════════════

termination = TextMentionTermination("TERMINATE")

team = SelectorGroupChat(
    participants=[search_expert, economy_expert, market_expert, semi_expert, integrator],
    model_client=model_client,
    termination_condition=termination,
    selector_prompt=(
        "반도체 주가 예측 멀티에이전트 시스템입니다.\n"
        "반드시 아래 순서를 따르세요. 순서를 건너뛰면 안 됩니다:\n\n"
        "1단계: SearchExpert (뉴스/공시 수집) — 반드시 tool 호출 필요\n"
        "2단계: EconomyExpert (거시경제 분석) — 반드시 tool 호출 필요\n"
        "3단계: MarketExpert (기술적 분석/수급) — 반드시 tool 호출 필요\n"
        "4단계: SemiExpert (반도체 기술 이벤트) — 반드시 tool 호출 필요\n"
        "5단계: Integrator (종합 판단) — 4개 에이전트 모두 tool 호출 완료 후에만 선택\n\n"
        "규칙:\n"
        "- 각 에이전트는 반드시 자신의 tool을 호출해야 합니다.\n"
        "- tool 호출 없이 텍스트만 생성하는 것은 금지됩니다.\n"
        "- 아직 tool을 호출하지 않은 에이전트가 있으면 Integrator를 선택하지 마세요.\n"
        "- SearchExpert가 완료되면 EconomyExpert, 그 다음 MarketExpert, 그 다음 SemiExpert 순서입니다.\n"
        "{roles}\n{participants}\n{history}"
    ),
)


# ═══════════════════════════════════════════════════════════════
# 실행
# ═══════════════════════════════════════════════════════════════

async def main(task: str):
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
    print(f" [시작] '{task}'")
    print("=" * 60)
    print()

    result = await Console(team.run_stream(task=task))

    # ── 보고서 파일 저장 ──
    from datetime import datetime

    reports_dir = os.path.join(BASE_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(reports_dir, f"report_{timestamp}.md")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# 주가 분석 보고서\n")
        f.write(f"- **분석 요청**: {task}\n")
        f.write(f"- **생성 시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("---\n\n")
        for msg in result.messages:
            source = getattr(msg, "source", "unknown")
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                f.write(f"## [{source}]\n\n{content}\n\n---\n\n")

    print()
    print(f"[보고서 저장 완료] {report_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = input("\n분석할 내용을 입력하세요: ").strip()
        if not task:
            task = "삼성전자 주가 전망을 분석해줘"

    asyncio.run(main(task))
