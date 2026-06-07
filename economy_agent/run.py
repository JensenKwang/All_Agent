"""
MacroAnalysisAgent 실행 스크립트

사용법:
    python run.py                               # 기본 질문으로 실행
    python run.py "미중 반도체 규제 영향은?"       # 질문 직접 입력
    python run.py --ingest                      # 6개월치 데이터 수집
    python run.py --ingest --months 36          # 3년치 전체 데이터 수집
    python run.py --ingest --no-fx-reports      # FX 리포트 크롤링 제외
    python run.py --crawl-reports               # FX 리포트만 크롤링 (3개월)
    python run.py --crawl-reports --months 12   # FX 리포트 12개월치 크롤링
    python run.py --news-only                   # 뉴스 RSS만 수집 (ECOS/FRED/리포트 제외)
"""

from __future__ import annotations

import json
import logging
import sys

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)  # 항상 run.py 옆의 .env를 로드

from macro_agent.agent import MacroAnalysisAgent
from macro_agent.db.pipeline import run_ingestion_pipeline
from macro_agent.db.timescale.client import initialize_schema
from macro_agent.tools.fx_report_crawler import (
    crawl_and_ingest_fx_reports,
    crawl_stats_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _parse_months(args: list[str], default: int) -> int:
    """--months N 플래그에서 N을 파싱"""
    if "--months" in args:
        idx = args.index("--months")
        try:
            return int(args[idx + 1])
        except (IndexError, ValueError):
            print("경고: --months 뒤에 숫자를 입력해주세요. 기본값을 사용합니다.", flush=True)
    return default


def run_ingest(months_back: int = 6, fetch_fx_reports: bool = True) -> None:
    """ECOS·FRED·뉴스·FX 리포트를 수집해 DB에 저장합니다."""
    print(f"=== TimescaleDB 스키마 초기화 ===", flush=True)
    initialize_schema()
    print(f"=== 데이터 수집 파이프라인 시작 (기간: {months_back}개월) ===", flush=True)
    result = run_ingestion_pipeline(
        months_back=months_back,
        fetch_fx_reports=fetch_fx_reports,
    )
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))


def run_news_only() -> None:
    """뉴스 RSS만 수집해 Vector DB에 저장합니다 (ECOS/FRED/리포트 제외)."""
    print("=== 뉴스 RSS 수집 시작 ===", flush=True)
    initialize_schema()
    result = run_ingestion_pipeline(
        months_back=1,
        fetch_news=True,
        fetch_fx_reports=False,
    )
    print(json.dumps(result.summary(), ensure_ascii=False, indent=2))


def run_crawl_reports(months_back: int = 3) -> None:
    """은행 FX 리포트 PDF만 크롤링해 Vector DB에 적재합니다."""
    print(f"=== 은행 FX 리포트 크롤링 시작 (기간: {months_back}개월) ===", flush=True)
    stats = crawl_and_ingest_fx_reports(months_back=months_back)
    print(json.dumps(crawl_stats_summary(stats), ensure_ascii=False, indent=2))


def run_agent(question: str) -> None:
    """에이전트에 질문을 던져 분석 결과를 출력합니다."""
    print(f"\n질문: {question}\n")
    agent = MacroAnalysisAgent(auto_init_db=False)
    result = agent.invoke(question)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--ingest" in args:
        months = _parse_months(args, default=6)
        fetch_fx = "--no-fx-reports" not in args
        run_ingest(months_back=months, fetch_fx_reports=fetch_fx)

    elif "--crawl-reports" in args:
        months = _parse_months(args, default=3)
        run_crawl_reports(months_back=months)

    elif "--news-only" in args:
        run_news_only()

    else:
        question = args[0] if args else "현재 반도체 업황과 미중 지정학 리스크를 분석해줘."
        run_agent(question)
