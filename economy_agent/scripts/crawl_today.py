"""
오늘의 최대 크롤링 스크립트

실행 순서:
    1. KCIF 신규 리포트 (최근 2개월 중 캐시에 없는 것)
    2. Source RSS 10개 피드 — Firecrawl 우선 본문 추출 (trafilatura 폴백)
       - 반도체 전문 7개: EE Times, Semiconductor Eng, Tom's Hardware,
         CNBC Tech, Digitimes, The Register, TechCrunch (geo_filter=False)
       - 종합 뉴스 3개: FT World, FT Technology, The Diplomat
         (geo_filter=True → 6대 지정학·규제 패턴 매칭 기사만 수집)
    3. Google News 47개 쿼리 — 헤드라인 수집
       (기존 33개 + 지정학·규제 패턴 심화 11개 + Bloomberg·Nikkei 보완 3개)
    4. FinBERT + spaCy NER — 미분석 기사 전체 처리
    5. ChromaDB Vector 적재 — clean_firecrawl_markdown 전처리 후 스마트 청킹

사용법:
    python scripts/crawl_today.py               # 전체 실행
    python scripts/crawl_today.py --skip-kcif   # KCIF 건너뜀
    python scripts/crawl_today.py --skip-gnews  # Google News 건너뜀
    python scripts/crawl_today.py --source-only # Source RSS 본문만
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from macro_agent.db.timescale.client import initialize_schema
from macro_agent.db.news_repository import get_article_stats

# crawl_news.py의 함수 직접 임포트
from crawl_news import (
    crawl_source_rss,
    crawl_gnews_daily,
    run_analysis_batch,
    run_vector_batch,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl_today")


def step_kcif() -> None:
    """KCIF 신규 리포트 — 최근 2개월 중 캐시에 없는 것만 다운로드."""
    from macro_agent.tools.fx_report_crawler import (
        crawl_and_ingest_fx_reports,
        crawl_stats_summary,
    )
    logger.info("━" * 60)
    logger.info("[STEP 1/5] KCIF 신규 리포트 크롤링 (months_back=2)")
    logger.info("━" * 60)
    stats = crawl_and_ingest_fx_reports(months_back=2)
    s = crawl_stats_summary(stats)["sources"][0]
    logger.info(
        "[KCIF 완료] 발견=%d  신규=%d  캐시스킵=%d  실패=%d  청크=%d",
        s["found"], s["downloaded"], s["skipped_cache"], s["failed"], s["vector_chunks"],
    )


def step_source_rss(max_per_feed: int) -> int:
    """Source RSS 7개 피드 — 실제 URL에서 본문 추출."""
    logger.info("━" * 60)
    logger.info("[STEP 2/5] Source RSS 본문 크롤링 (최대 %d건/피드 × 10피드)", max_per_feed)
    logger.info("━" * 60)
    total = crawl_source_rss(max_per_feed=max_per_feed)
    logger.info("[Source RSS 완료] 신규 %d건 저장", total)
    return total


def step_gnews(max_items: int) -> int:
    """Google News 33개 쿼리 — 헤드라인 + 요약 수집."""
    logger.info("━" * 60)
    logger.info("[STEP 3/5] Google News 헤드라인 크롤링 (쿼리당 최대 %d건 × 47쿼리)", max_items)
    logger.info("━" * 60)
    total = crawl_gnews_daily(max_items=max_items)
    logger.info("[Google News 완료] 신규 %d건 저장", total)
    return total


def step_analyze() -> int:
    """FinBERT + spaCy NER — 미분석 기사 전체 처리 (루프)."""
    logger.info("━" * 60)
    logger.info("[STEP 4/5] FinBERT + NER 분석 (미분석 기사 전체)")
    logger.info("━" * 60)
    total = 0
    while True:
        n = run_analysis_batch(batch_size=200)
        total += n
        if n == 0:
            break
    logger.info("[분석 완료] 총 %d건", total)
    return total


def step_vectorize() -> int:
    """ChromaDB 스마트 청킹 + 임베딩 — 미적재 기사 전체 (루프)."""
    logger.info("━" * 60)
    logger.info("[STEP 5/5] ChromaDB Vector 적재 (미적재 기사 전체)")
    logger.info("━" * 60)
    total = 0
    while True:
        n = run_vector_batch(batch_size=200)
        total += n
        if n == 0:
            break
    logger.info("[Vector 완료] 총 %d건 적재", total)
    return total


def print_stats(label: str) -> None:
    s = get_article_stats()
    logger.info(
        "[통계 %s] 총=%d건  본문=%d건  분석=%d건  Vector=%d건",
        label, s["total"], s["has_body"], s["analyzed"], s["vector_ingested"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="오늘의 최대 크롤링 스크립트")
    parser.add_argument("--skip-kcif",   action="store_true", help="KCIF 크롤링 건너뜀")
    parser.add_argument("--skip-gnews",  action="store_true", help="Google News 건너뜀")
    parser.add_argument("--source-only", action="store_true", help="Source RSS 본문만 수집")
    parser.add_argument("--max-per-feed", type=int, default=50,
                        help="Source RSS 피드당 최대 기사 수 (기본: 50)")
    parser.add_argument("--max-gnews", type=int, default=100,
                        help="Google News 쿼리당 최대 기사 수 (기본: 100)")
    args = parser.parse_args()

    initialize_schema()
    print_stats("시작 전")

    if not args.skip_kcif:
        step_kcif()

    step_source_rss(max_per_feed=args.max_per_feed)

    if not args.source_only and not args.skip_gnews:
        step_gnews(max_items=args.max_gnews)

    step_analyze()
    step_vectorize()

    print_stats("완료 후")
    logger.info("=== crawl_today 전체 완료 ===")


if __name__ == "__main__":
    main()
