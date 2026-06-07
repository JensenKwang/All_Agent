import os
import sys
from typing import Annotated
from typing_extensions import TypedDict
from dotenv import load_dotenv

load_dotenv()
if not os.getenv("OPENAI_API_KEY"):
    print("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
    sys.exit(1)

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from database import SessionLocal
from models import News, Reporter, Company, Disclosure, AgentResponse, ReliabilityLog
from reliability import compute_and_save

# ── State ─────────────────────────────────────────────────────────────────────

class State(TypedDict):
    messages: Annotated[list, add_messages]
    query: str      # 원본 사용자 질문 (AgentResponse 저장용)
    model: str      # 사용 모델명 (실험 비교용)


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_news_by_keyword(keyword: str) -> str:
    """
    키워드로 DB에서 반도체 관련 뉴스를 검색합니다.
    제목/설명에서 매칭되는 최신 뉴스 10개를 반환합니다.
    """
    db = SessionLocal()
    try:
        query_str = f"%{keyword.replace(' ', '%')}%"
        news_list = (
            db.query(News)
            .filter((News.title.like(query_str)) | (News.description.like(query_str)))
            .order_by(News.id.desc())
            .limit(10)
            .all()
        )

        if not news_list:
            news_list = db.query(News).order_by(News.id.desc()).limit(5).all()
            if not news_list:
                return "DB에 저장된 데이터가 없습니다."

        results = []
        for n in news_list:
            log = db.query(ReliabilityLog).filter_by(news_id=n.id).first()
            if not log:
                compute_and_save(n, db)
                db.commit()
                log = db.query(ReliabilityLog).filter_by(news_id=n.id).first()

            results.append({
                "뉴스_ID": n.id,
                "기사_제목": n.title,
                "작성_기자": n.reporter.name if n.reporter else "Unknown",
                "언론사": n.press.name if n.press else "Unknown",
                "신뢰도_최종": log.final_score if log else None,
                "신뢰도_언론사": log.press_score if log else None,
                "신뢰도_기자": log.reporter_score if log else None,
                "신뢰도_최신성": log.freshness if log else None,
                "요약": n.summary,
                "감성점수": n.sentiment_score,
                "게재일": n.pub_date,
                "URL": n.url,
            })
        return str(results)
    finally:
        db.close()


@tool
def check_reporter_reliability(reporter_name: str) -> str:
    """
    기자의 신뢰도 점수, 정정 이력, 이메일 정보를 DB에서 조회합니다.
    """
    db = SessionLocal()
    try:
        rep = db.query(Reporter).filter(Reporter.name == reporter_name).first()
        if not rep:
            return f"'{reporter_name}' 기자 정보를 DB에서 찾지 못했습니다."
        return str({
            "기자_이름": rep.name,
            "신뢰도_점수": rep.reporter_score,
            "정정_횟수": rep.correction_count,
            "이메일": rep.email or "없음",
        })
    finally:
        db.close()


@tool
def get_disclosure_by_company(company_name: str) -> str:
    """
    기업명으로 DART 공시 데이터를 검색합니다. 최신 공시 5건을 반환합니다.
    """
    db = SessionLocal()
    try:
        company = db.query(Company).filter(
            Company.corp_name.like(f"%{company_name}%")
        ).first()
        if not company:
            return f"'{company_name}' 기업의 공시 데이터가 없습니다."

        disclosures = (
            db.query(Disclosure)
            .filter(Disclosure.company_id == company.id)
            .order_by(Disclosure.id.desc())
            .limit(5)
            .all()
        )
        results = [
            {"공시제목": d.title, "공시유형": d.report_type, "공시일": d.filed_at}
            for d in disclosures
        ]
        return str(results)
    finally:
        db.close()


tools = [get_news_by_keyword, check_reporter_reliability, get_disclosure_by_company]

# ── LLM ───────────────────────────────────────────────────────────────────────

def get_llm(model_name: str = "gpt-4o-mini"):
    return ChatOpenAI(model=model_name, temperature=0).bind_tools(tools)


SYSTEM_PROMPT = """너는 반도체 산업 전문 뉴스 분석 에이전트야.
반드시 DB에서 수집된 데이터만 근거로 사용하고, 외부 지식은 배제해.

[답변 규칙]
1. 기사 요약을 먼저 가독성 좋게 제시할 것.
2. 각 기사마다 신뢰도 점수를 표시할 것:
   - 종합 신뢰도(신뢰도_최종), 언론사(신뢰도_언론사), 기자(신뢰도_기자), 최신성(신뢰도_최신성)
   - 기자가 Unknown이면 "기자 미확인"으로 표시할 것.
3. 정정 이력이 있는 기자 기사에만 ⚠️ 표시 + "과거 N건의 정정 보도 이력" 명시.
4. 관련 공시 데이터가 있으면 get_disclosure_by_company로 함께 조회할 것.
5. 기사별 신뢰도가 이미 표시됐으므로 마지막에 기자 신뢰도를 별도로 반복하지 말 것.
"""

# ── Nodes ─────────────────────────────────────────────────────────────────────

def agent_node(state: State):
    model_name = state.get("model", "gpt-4o-mini")
    llm = get_llm(model_name)

    messages = state["messages"]
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + messages

    response = llm.invoke(messages)
    return {"messages": [response]}


tool_node = ToolNode(tools)


def save_response_node(state: State):
    """최종 답변을 AgentResponse 테이블에 저장합니다."""
    final_content = ""
    for m in reversed(state["messages"]):
        if hasattr(m, "content") and not getattr(m, "tool_calls", None):
            content = m.content
            if isinstance(content, list):
                content = "".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            final_content = content
            break

    db = SessionLocal()
    try:
        record = AgentResponse(
            query=state.get("query", ""),
            model_name=state.get("model", "gpt-4o-mini"),
            response=final_content,
        )
        db.add(record)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[저장 오류] {e}")
    finally:
        db.close()

    return {}


# ── Graph ──────────────────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(State)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_node("save", save_response_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        tools_condition,
        {"tools": "tools", END: "save"},
    )
    graph.add_edge("tools", "agent")
    graph.add_edge("save", END)

    return graph.compile()


app = build_graph()


# ── CLI ───────────────────────────────────────────────────────────────────────

def start_chat(model_name: str = "gpt-4o-mini"):
    print("=" * 60)
    print(f" 반도체 뉴스 분석 에이전트 (LangGraph + {model_name})")
    print("=" * 60)
    print("종료하려면 '종료' 입력\n")

    chat_history = []

    while True:
        try:
            user_input = input(">> 당신: ").strip()
            if not user_input:
                continue
            if user_input in ["종료", "exit", "quit"]:
                print("에이전트를 종료합니다.")
                break

            chat_history.append(HumanMessage(content=user_input))
            print("분석 중...\n")

            result = app.invoke({
                "messages": chat_history,
                "query": user_input,
                "model": model_name,
            })

            # 마지막 AI 답변 추출 및 출력
            for m in reversed(result["messages"]):
                if hasattr(m, "content") and not getattr(m, "tool_calls", None):
                    content = m.content
                    if isinstance(content, list):
                        content = "".join(
                            c.get("text", "") if isinstance(c, dict) else str(c)
                            for c in content
                        )
                    print(f"[Agent]\n{'-' * 50}\n{content}\n{'-' * 50}\n")
                    chat_history.append(m)
                    break

        except KeyboardInterrupt:
            print("\n강제 종료")
            break
        except Exception as e:
            print(f"오류: {e}")


if __name__ == "__main__":
    # 모델 바꾸려면 인자 변경: "gpt-4o-mini", "gpt-4o-mini", "gpt-3.5-turbo" 등
    start_chat(model_name="gpt-4o-mini")
