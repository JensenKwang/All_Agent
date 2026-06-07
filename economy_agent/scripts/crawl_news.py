"""
멀티레이어 반도체·거시경제 뉴스 크롤러

적재 파이프라인 (3단계):
    Layer 1 — PostgreSQL (news_articles): 원문 + 메타데이터 영구 저장
    Layer 2 — FinBERT + spaCy NER:        감성 점수·엔티티 DB 인덱스
    Layer 3 — ChromaDB (vector):           스마트 청킹 + 임베딩 RAG 저장

소스 전략:
    A) Source RSS 피드 (실제 URL → trafilatura 본문 추출):
       EE Times, Semiconductor Engineering, Tom's Hardware, CNBC, Digitimes,
       The Register, TechCrunch
    B) Google News RSS (날짜 필터 지원, 헤드라인+요약만):
       33개 한/영 쿼리 × 2주 단위 구간 분할

사용법:
    # 일간 자동화 (매일 오전 9시)
    python scripts/crawl_news.py

    # 과거 6개월 수집
    python scripts/crawl_news.py --historical --months-back 6

    # 특정 기간 지정
    python scripts/crawl_news.py --historical --date-from 2025-01-01 --date-to 2025-06-30

    # 소스 RSS만 수집 (Google News 스킵)
    python scripts/crawl_news.py --source-only

    # Google News만 수집 (소스 RSS 스킵)
    python scripts/crawl_news.py --gnews-only

    # FinBERT·NER 분석만 실행 (크롤 없이)
    python scripts/crawl_news.py --analyze-only

    # Vector DB 적재만 실행
    python scripts/crawl_news.py --vectorize-only
"""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import feedparser
import requests
import trafilatura

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from macro_agent.db.news_repository import (
    ArticleRow,
    get_article_stats,
    get_not_vector_ingested,
    get_unanalyzed_articles,
    mark_vector_ingested,
    update_analysis,
    upsert_article,
    url_exists,
)
from macro_agent.db.timescale.client import initialize_schema
from macro_agent.db.vector.repository import ingest_text_to_vector_db
from macro_agent.db.vector.smart_chunker import clean_firecrawl_markdown
from macro_agent.tools.firecrawl_fetcher import (
    fetch_article_result,
    is_enabled as firecrawl_enabled,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("crawl_news")

# ── 상수 ─────────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_RSS_BASE = "https://news.google.com/rss/search"

# ── Source RSS 피드 ──────────────────────────────────────────────────────────
#
# geo_filter=False : 반도체 전문 미디어 — 전기사 수집
# geo_filter=True  : 종합 뉴스 — 6대 지정학·규제 키워드 매칭 기사만 수집
#
# Bloomberg: 공개 RSS 미제공 → Google News 타겟 쿼리(_QUERIES)로 대체

_SOURCE_RSS: list[dict] = [
    # ── 반도체 전문 미디어 (geo_filter=False) ──────────────────────────────
    {
        "name": "EE Times",
        "url": "https://www.eetimes.com/feed/",
        "lang": "en",
        "geo_filter": False,
    },
    {
        "name": "Semiconductor Engineering",
        "url": "https://semiengineering.com/feed/",
        "lang": "en",
        "geo_filter": False,
    },
    {
        "name": "Tom's Hardware",
        "url": "https://www.tomshardware.com/feeds/all",
        "lang": "en",
        "geo_filter": False,
    },
    {
        "name": "CNBC Technology",
        "url": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
        "lang": "en",
        "geo_filter": False,
    },
    {
        "name": "Digitimes",
        "url": "https://www.digitimes.com/rss/daily.xml",
        "lang": "en",
        "geo_filter": False,
    },
    {
        "name": "The Register",
        "url": "https://www.theregister.com/headlines.atom",
        "lang": "en",
        "geo_filter": False,
    },
    {
        "name": "TechCrunch",
        "url": "https://techcrunch.com/feed/",
        "lang": "en",
        "geo_filter": False,
    },
    # ── 종합 뉴스·지정학 (geo_filter=True) ──────────────────────────────
    # Reuters·Nikkei Asia: 공개 RSS 폐지됨 → 아래 3개 소스로 대체
    {
        "name": "Financial Times World",
        "url": "https://www.ft.com/world?format=rss",
        "lang": "en",
        "geo_filter": True,
    },
    {
        "name": "Financial Times Technology",
        "url": "https://www.ft.com/technology?format=rss",
        "lang": "en",
        "geo_filter": True,
    },
    {
        "name": "The Diplomat",
        "url": "https://thediplomat.com/feed/",
        "lang": "en",
        "geo_filter": True,
    },
]

# ── Google News 쿼리 목록 ─────────────────────────────────────────────────────

_QUERIES: list[tuple[str, str, str]] = [
    # 지정학·규제 (영문)
    ("semiconductor export control US China BIS", "en", "US"),
    ("chip war geopolitical supply chain disruption", "en", "US"),
    ("Taiwan Strait TSMC military risk semiconductor", "en", "US"),
    ("CHIPS Act semiconductor subsidy fab", "en", "US"),
    ("China semiconductor restriction Huawei advanced chip", "en", "US"),
    # 업황·사이클 (영문)
    ("DRAM NAND memory chip price inventory cycle", "en", "US"),
    ("HBM high bandwidth memory AI demand Nvidia", "en", "US"),
    ("semiconductor fab capacity utilization wafer start", "en", "US"),
    ("foundry TSMC Samsung Intel market share node", "en", "US"),
    ("semiconductor industry outlook earnings guidance", "en", "US"),
    # 기업·실적 (영문)
    ("TSMC revenue profit guidance semiconductor", "en", "US"),
    ("Samsung Electronics semiconductor chip profit loss", "en", "US"),
    ("SK Hynix memory chip earnings results", "en", "US"),
    ("Nvidia AMD GPU AI chip demand data center", "en", "US"),
    ("SOX Philadelphia semiconductor index stock", "en", "US"),
    # 거시·금융 (영문)
    ("Federal Reserve rate cut hike technology semiconductor", "en", "US"),
    ("USD KRW exchange rate Korean semiconductor export", "en", "US"),
    ("US inflation CPI PPI semiconductor manufacturing", "en", "US"),
    # 지정학·규제 (한글)
    ("반도체 수출 규제 미중 갈등 무역", "ko", "KR"),
    ("대만해협 반도체 공급망 리스크 지정학", "ko", "KR"),
    ("미국 칩법 CHIPS Act 반도체 보조금 투자", "ko", "KR"),
    ("중국 반도체 제재 화웨이 첨단칩 규제", "ko", "KR"),
    # 업황·사이클 (한글)
    ("반도체 경기 사이클 재고 조정 회복", "ko", "KR"),
    ("DRAM 낸드 메모리 반도체 가격 수급", "ko", "KR"),
    ("HBM 고대역폭메모리 AI 반도체 수요", "ko", "KR"),
    ("반도체 수출 한국 무역수지 월별", "ko", "KR"),
    ("파운드리 생산능력 가동률 반도체", "ko", "KR"),
    # 기업·실적 (한글)
    ("삼성전자 반도체 실적 영업이익 HBM", "ko", "KR"),
    ("SK하이닉스 메모리 반도체 실적 매출", "ko", "KR"),
    ("TSMC 파운드리 수익 가이던스 한국", "ko", "KR"),
    # 거시·금융 (한글)
    ("원달러 환율 반도체 수출 영향 외환", "ko", "KR"),
    ("한국은행 기준금리 반도체 제조업 경기", "ko", "KR"),
    ("미 연준 금리 반도체지수 기술주", "ko", "KR"),
    # ── 6대 지정학·규제 패턴 심화 쿼리 (영문) ──────────────────────────────
    # Pattern 1: semiconductor + sanction/export control/BIS EAR
    ("semiconductor \"export control\" BIS EAR sanction", "en", "US"),
    # Pattern 2: supply chain + disruption/restriction/friend-shoring
    ("\"supply chain\" disruption restriction \"friend-shoring\" chip semiconductor", "en", "US"),
    # Pattern 3: Taiwan Strait / cross-strait / South China Sea
    ("\"Taiwan Strait\" semiconductor military supply chain risk", "en", "US"),
    ("\"South China Sea\" technology trade chip disruption", "en", "US"),
    # Pattern 4: critical minerals / gallium / germanium / rare earths
    ("\"critical minerals\" gallium germanium \"rare earths\" China semiconductor", "en", "US"),
    # Pattern 5: Chips Act / tariff retaliation
    ("\"Chips Act\" semiconductor fab subsidy investment", "en", "US"),
    ("\"tariff retaliation\" technology semiconductor trade China", "en", "US"),
    # Pattern 6: military conflict / geopolitical risk + tech
    ("\"geopolitical risk\" semiconductor technology chip supply chain", "en", "US"),
    ("\"military conflict\" Taiwan chip technology supply chain", "en", "US"),
    # Bloomberg·Nikkei 보완 쿼리 (공개 RSS 없어 Google News로 대체)
    ("Bloomberg semiconductor geopolitics chip export control", "en", "US"),
    ("Nikkei Asia semiconductor supply chain chip technology", "en", "US"),
    # ── 6대 지정학·규제 패턴 심화 쿼리 (한글) ──────────────────────────────
    ("희토류 갈륨 게르마늄 반도체 수출규제 중국", "ko", "KR"),
    ("지정학 리스크 반도체 기술 공급망 위기 규제", "ko", "KR"),
    ("대만해협 군사 갈등 반도체 공급망 위기", "ko", "KR"),
]


# ── 텍스트 유틸리티 ───────────────────────────────────────────────────────────

def _clean_text(raw: str) -> str:
    """HTML 태그 제거 + 엔티티 디코딩 + 연속 공백 정리."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_rss_date(raw: str) -> date | None:
    """RSS RFC 2822 또는 YYYY-MM-DD 날짜를 date 객체로 변환합니다."""
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except Exception:
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except Exception:
                pass
    return None


# ── 지정학 필터 ──────────────────────────────────────────────────────────────

def _matches_geo_filter(text: str) -> bool:
    """
    6가지 지정학·규제 키워드 패턴 중 하나라도 매칭되면 True를 반환합니다.
    Reuters·Nikkei 등 geo_filter=True 소스에서 관련 기사만 선별하는 데 사용합니다.

    패턴:
        1. (semiconductor | chip) + (sanction | export control | BIS EAR)
        2. supply chain + (disruption | restriction | friend-shoring)
        3. Taiwan Strait | cross-strait | South China Sea
        4. critical minerals | gallium | germanium | rare earths
        5. Chips Act | tariff retaliation
        6. military conflict | (geopolitical risk + tech/chip/semiconductor/supply)
    """
    t = text.lower()

    # Rule 1
    if ("semiconductor" in t or "chip" in t) and any(
        k in t for k in ("sanction", "export control", "bis ear")
    ):
        return True

    # Rule 2
    if "supply chain" in t and any(
        k in t for k in ("disruption", "restriction", "friend-shoring", "friendshoring")
    ):
        return True

    # Rule 3
    if any(k in t for k in ("taiwan strait", "cross-strait", "south china sea")):
        return True

    # Rule 4
    if any(k in t for k in ("critical mineral", "gallium", "germanium", "rare earth")):
        return True

    # Rule 5
    if any(k in t for k in ("chips act", "tariff retaliation")):
        return True

    # Rule 6
    if "military conflict" in t:
        return True
    if "geopolitical risk" in t and any(
        k in t for k in ("tech", "chip", "semiconductor", "supply")
    ):
        return True

    return False


# ── Layer 1: Source RSS 크롤링 (본문 추출) ────────────────────────────────────

def _fetch_body(url: str) -> str | None:
    """trafilatura로 기사 본문을 추출합니다. 실패 시 None 반환."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        body = trafilatura.extract(
            resp.text,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if body and len(body.strip()) > 200:
            return body.strip()
    except Exception as exc:
        logger.debug("본문 추출 실패 (%s): %s", url[:60], exc)
    return None


def _fetch_body_with_fc_fallback(url: str) -> tuple[str | None, str | None]:
    """
    기사 본문을 Firecrawl 우선으로 수집하고, 실패 시 trafilatura로 폴백합니다.

    Returns:
        (body_text, published_date_"YYYY-MM-DD"_or_None)
        published_date는 Firecrawl에서만 추출되며 trafilatura 폴백 시 None.
    """
    if firecrawl_enabled():
        result = fetch_article_result(url)
        if result["body"]:
            logger.debug(
                "Firecrawl 본문 수집 (len=%d, date=%s) url=%r",
                len(result["body"]), result["published_date"] or "없음", url[:60],
            )
            return result["body"], result["published_date"]
        logger.debug("Firecrawl 본문 없음 → trafilatura 폴백 url=%r", url[:60])

    return _fetch_body(url), None


def crawl_source_rss(max_per_feed: int = 50) -> int:
    """
    소스 RSS 피드를 크롤하고 본문을 추출하여 PostgreSQL에 저장합니다.

    본문 수집 우선순위:
        1. Firecrawl API (FIRECRAWL_API_KEY 설정 시) — 마크다운 전문 + 발행일
        2. trafilatura — HTML 파싱 평문 본문
        3. RSS summary(1000자) — 본문 추출 실패 시 폴백

    geo_filter=True 소스(Reuters, Nikkei Asia):
        제목+요약이 6대 지정학·규제 패턴 중 하나를 포함하는 기사만 수집합니다.
        본문 수집(Firecrawl/trafilatura) 전에 필터링하여 API 크레딧을 절약합니다.

    Returns:
        신규 저장 건수
    """
    total_new = 0
    for source in _SOURCE_RSS:
        name = source["name"]
        lang = source["lang"]
        apply_geo = bool(source.get("geo_filter"))
        logger.info("[Source RSS] %s 크롤 중... (geo_filter=%s)", name, apply_geo)

        try:
            resp = requests.get(source["url"], headers=_HEADERS, timeout=12)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
        except Exception as exc:
            logger.warning("[Source RSS] %s 피드 오류: %s", name, exc)
            continue

        new_count = 0
        geo_skipped = 0
        for entry in feed.entries[:max_per_feed]:
            url = entry.get("link", "")
            if not url or url_exists(url):
                continue

            title = _clean_text(entry.get("title", ""))
            if not title:
                continue

            # ── 지정학 필터 (geo_filter=True 소스만) ──────────────────────
            if apply_geo:
                preview = f"{title} {_clean_text(entry.get('summary', ''))}"
                if not _matches_geo_filter(preview):
                    geo_skipped += 1
                    continue

            published_date = _parse_rss_date(entry.get("published", ""))
            author_list = entry.get("authors", [])
            author = author_list[0].get("name", "") if author_list else ""

            # ── 본문 추출: Firecrawl 우선 → trafilatura 폴백 ──────────────
            body, fc_date = _fetch_body_with_fc_fallback(url)

            # Firecrawl 발행일로 RSS 날짜 보완 (HTML 메타태그가 더 정확)
            if fc_date and not published_date:
                try:
                    from datetime import datetime as _dt
                    published_date = _dt.strptime(fc_date, "%Y-%m-%d").date()
                except ValueError:
                    pass

            summary = _clean_text(entry.get("summary", ""))[:1000] if not body else None

            article = ArticleRow(
                url=url,
                title=title,
                body=body,
                summary=summary or None,
                publisher=name,
                author=author or None,
                published_date=published_date,
                lang=lang,
                query_tag=f"source_rss:{name}",
            )
            article_id = upsert_article(article)
            if article_id:
                new_count += 1

            time.sleep(0.5)  # 소스 서버 부하 방지

        if apply_geo:
            logger.info(
                "[Source RSS] %s → 신규 %d건 (geo 필터 스킵 %d건)",
                name, new_count, geo_skipped,
            )
        else:
            logger.info("[Source RSS] %s → 신규 %d건", name, new_count)
        total_new += new_count
        time.sleep(1.0)

    return total_new


# ── Layer 1: Google News RSS 크롤링 (헤드라인) ───────────────────────────────

def _build_gnews_url(query: str, lang: str, country: str,
                     date_from: str | None, date_to: str | None) -> str:
    """Google News RSS URL (콜론 percent-encoding 방지)."""
    q_parts = [query.replace(" ", "+")]
    if date_from:
        q_parts.append(f"after:{date_from}")
    if date_to:
        q_parts.append(f"before:{date_to}")
    q_str = "+".join(q_parts)
    return f"{_RSS_BASE}?q={q_str}&hl={lang}&gl={country}&ceid={country}:{lang}"


def _fetch_gnews_one(query: str, lang: str, country: str,
                     date_from: str | None = None,
                     date_to: str | None = None,
                     max_items: int = 100) -> int:
    """단일 Google News 쿼리로 헤드라인을 수집하고 PostgreSQL에 저장합니다."""
    url = _build_gnews_url(query, lang, country, date_from, date_to)
    try:
        resp = requests.get(url, timeout=12, headers=_HEADERS)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:
        logger.warning("[GNews] 쿼리 오류 (%r): %s", query[:40], exc)
        return 0

    new_count = 0
    for entry in feed.entries[:max_items]:
        gnews_url = entry.get("link", "")
        if not gnews_url:
            continue

        # Google News CBMi URL은 본문 추출 불가 — URL 자체를 식별자로 사용
        if url_exists(gnews_url):
            continue

        source_info = entry.get("source", {})
        publisher = source_info.get("title", "Google News") if isinstance(source_info, dict) else "Google News"
        title = _clean_text(entry.get("title", ""))
        summary = _clean_text(entry.get("summary", ""))[:600]
        published_date = _parse_rss_date(entry.get("published", ""))

        if not title:
            continue

        article = ArticleRow(
            url=gnews_url,
            title=title,
            body=None,
            summary=summary or None,
            publisher=publisher,
            author=None,
            published_date=published_date,
            lang=lang,
            query_tag=query[:100],
        )
        article_id = upsert_article(article)
        if article_id:
            new_count += 1

    return new_count


def _biweekly_windows(date_from: datetime, date_to: datetime) -> list[tuple[str, str]]:
    """date_from ~ date_to 구간을 14일 단위로 분할합니다."""
    windows: list[tuple[str, str]] = []
    cursor = date_from
    while cursor < date_to:
        window_end = min(cursor + timedelta(days=14), date_to)
        windows.append((
            cursor.strftime("%Y-%m-%d"),
            window_end.strftime("%Y-%m-%d"),
        ))
        cursor = window_end + timedelta(days=1)
    return windows


def crawl_gnews_daily(max_items: int = 100) -> int:
    """날짜 필터 없이 최신 Google News 기사를 수집합니다."""
    total = 0
    for i, (query, lang, country) in enumerate(_QUERIES, 1):
        n = _fetch_gnews_one(query, lang, country, max_items=max_items)
        total += n
        logger.info("[GNews 일간 %d/%d] %r → 신규 %d건", i, len(_QUERIES), query[:50], n)
        time.sleep(0.8)
    return total


def crawl_gnews_historical(date_from: datetime, date_to: datetime,
                           max_items: int = 100) -> int:
    """날짜 구간을 2주 단위로 분할하여 과거 Google News 기사를 수집합니다."""
    windows = _biweekly_windows(date_from, date_to)
    logger.info("[GNews 과거] %s ~ %s → %d개 구간, 쿼리 %d개",
                date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"),
                len(windows), len(_QUERIES))
    total = 0
    for w_idx, (w_from, w_to) in enumerate(windows, 1):
        logger.info("[GNews 구간 %d/%d] %s ~ %s", w_idx, len(windows), w_from, w_to)
        for query, lang, country in _QUERIES:
            n = _fetch_gnews_one(query, lang, country,
                                 date_from=w_from, date_to=w_to,
                                 max_items=max_items)
            total += n
            time.sleep(1.0)
        logger.info("  구간 완료 — 누적 신규 %d건", total)
        if w_idx < len(windows):
            time.sleep(2.0)
    return total


# ── Layer 2: FinBERT + NER 분석 ──────────────────────────────────────────────

def run_analysis_batch(batch_size: int = 50) -> int:
    """
    미분석 기사를 배치로 FinBERT + spaCy NER 분석하고 DB에 저장합니다.

    Returns:
        분석 완료 건수
    """
    from macro_agent.analysis.news_analyzer import analyze_article

    articles = get_unanalyzed_articles(limit=batch_size)
    if not articles:
        logger.info("[분석] 미분석 기사 없음")
        return 0

    logger.info("[분석] FinBERT + NER 처리 시작 (%d건)...", len(articles))
    done = 0
    for art in articles:
        article_id: int = art["id"]
        lang: str = art.get("lang", "en")
        text: str = art.get("body") or art.get("summary") or art.get("title", "")

        if not text.strip():
            continue

        try:
            result = analyze_article(text=text, lang=lang)
            update_analysis(
                article_id=article_id,
                sentiment_pos=result["sentiment_pos"],
                sentiment_neg=result["sentiment_neg"],
                sentiment_neu=result["sentiment_neu"],
                entities=result["entities"],
                keywords=result["keywords"],
            )
            done += 1
        except Exception as exc:
            logger.warning("[분석] 오류 (id=%d): %s", article_id, exc)

    logger.info("[분석] 완료 %d/%d건", done, len(articles))
    return done


# ── Layer 3: ChromaDB Vector 적재 ────────────────────────────────────────────

def run_vector_batch(batch_size: int = 100) -> int:
    """
    Vector DB 미적재 기사를 스마트 청킹하여 ChromaDB에 저장합니다.

    Returns:
        적재 완료 기사 건수
    """
    articles = get_not_vector_ingested(limit=batch_size)
    if not articles:
        logger.info("[Vector] 미적재 기사 없음")
        return 0

    logger.info("[Vector] ChromaDB 적재 시작 (%d건)...", len(articles))
    done = 0
    for art in articles:
        article_id: int = art["id"]
        lang: str = art.get("lang", "en")
        publisher: str = art.get("publisher") or "Unknown"
        pub_date = art.get("published_date")

        title: str = art.get("title", "")
        body: str | None = art.get("body")
        summary: str | None = art.get("summary")

        # Firecrawl/trafilatura 본문 보일러플레이트 제거
        # (trafilatura 평문에는 패턴이 매칭되지 않으므로 항상 안전하게 실행)
        if body:
            body = clean_firecrawl_markdown(body) or body

        text = body or summary or title
        if not text:
            continue

        if body:
            full_text = f"{title}\n\n{body}"
        else:
            full_text = f"{title}\n\n{summary}" if summary else title

        try:
            chunks = ingest_text_to_vector_db(
                text=full_text,
                metadata={
                    "source_name":    publisher,
                    "published_date": str(pub_date) if pub_date else "",
                    "url":            art.get("url", ""),
                    "tags":           art.get("keywords") or [],
                },
                source_type="news",
                lang=lang,
            )
            mark_vector_ingested(article_id, chunks)
            done += 1
        except Exception as exc:
            logger.warning("[Vector] 적재 실패 (id=%d): %s", article_id, exc)

    logger.info("[Vector] 완료 %d/%d건", done, len(articles))
    return done


# ── 메인 파이프라인 ───────────────────────────────────────────────────────────

def run_daily(max_items: int = 100, source_only: bool = False,
              gnews_only: bool = False) -> None:
    """일간 자동화: Source RSS + Google News + 분석 + Vector 적재."""
    logger.info("=== 일간 뉴스 파이프라인 시작 ===")
    stats_before = get_article_stats()
    logger.info("현황: 총 %d건 / 본문 %d건 / 분석됨 %d건 / Vector %d건",
                stats_before["total"], stats_before["has_body"],
                stats_before["analyzed"], stats_before["vector_ingested"])

    # Phase A: 소스 RSS (본문 있음)
    if not gnews_only:
        new_source = crawl_source_rss(max_per_feed=max_items)
        logger.info("[Phase A] Source RSS 신규 %d건", new_source)

    # Phase B: Google News RSS (헤드라인)
    if not source_only:
        new_gnews = crawl_gnews_daily(max_items=max_items)
        logger.info("[Phase B] Google News 신규 %d건", new_gnews)

    # Phase C: FinBERT + NER 분석
    analyzed = run_analysis_batch(batch_size=200)
    logger.info("[Phase C] 분석 완료 %d건", analyzed)

    # Phase D: Vector DB 적재
    vectorized = run_vector_batch(batch_size=300)
    logger.info("[Phase D] Vector 적재 완료 %d건", vectorized)

    stats_after = get_article_stats()
    logger.info(
        "=== 일간 완료 — 총 %d건 / 본문 %d건 / 분석됨 %d건 / Vector %d건 ===",
        stats_after["total"], stats_after["has_body"],
        stats_after["analyzed"], stats_after["vector_ingested"],
    )


def run_historical(date_from: datetime, date_to: datetime,
                   max_items: int = 100, source_only: bool = False,
                   gnews_only: bool = False) -> None:
    """과거 데이터 수집: Source RSS + Google News 과거 쿼리 + 분석 + Vector 적재."""
    logger.info("=== 과거 뉴스 파이프라인 시작 %s ~ %s ===",
                date_from.strftime("%Y-%m-%d"), date_to.strftime("%Y-%m-%d"))

    if not gnews_only:
        new_source = crawl_source_rss(max_per_feed=max_items)
        logger.info("[과거 Phase A] Source RSS 신규 %d건", new_source)

    if not source_only:
        new_gnews = crawl_gnews_historical(date_from, date_to, max_items=max_items)
        logger.info("[과거 Phase B] Google News 신규 %d건", new_gnews)

    analyzed = run_analysis_batch(batch_size=500)
    logger.info("[과거 Phase C] 분석 완료 %d건", analyzed)

    vectorized = run_vector_batch(batch_size=500)
    logger.info("[과거 Phase D] Vector 적재 완료 %d건", vectorized)

    stats = get_article_stats()
    logger.info(
        "=== 과거 완료 — 총 %d건 / 본문 %d건 / 분석됨 %d건 / Vector %d건 ===",
        stats["total"], stats["has_body"], stats["analyzed"], stats["vector_ingested"],
    )


# ── CLI ──────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="반도체·거시경제 멀티레이어 뉴스 크롤러",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--historical", action="store_true",
                        help="과거 데이터 수집 모드")
    parser.add_argument("--months-back", type=int, default=6, metavar="N",
                        help="과거 N개월치 수집 (기본값: 6)")
    parser.add_argument("--date-from", metavar="YYYY-MM-DD",
                        help="수집 시작일")
    parser.add_argument("--date-to", metavar="YYYY-MM-DD",
                        help="수집 종료일 (기본값: 오늘)")
    parser.add_argument("--max-items", type=int, default=100, metavar="N",
                        help="쿼리/피드당 최대 수집 수 (기본값: 100)")
    parser.add_argument("--source-only", action="store_true",
                        help="Source RSS 피드만 수집 (Google News 스킵)")
    parser.add_argument("--gnews-only", action="store_true",
                        help="Google News RSS만 수집 (Source RSS 스킵)")
    parser.add_argument("--analyze-only", action="store_true",
                        help="크롤 없이 미분석 기사만 FinBERT+NER 처리")
    parser.add_argument("--vectorize-only", action="store_true",
                        help="크롤/분석 없이 미적재 기사만 Vector DB에 적재")
    parser.add_argument("--stats", action="store_true",
                        help="현황 통계만 출력")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    initialize_schema()

    if args.stats:
        stats = get_article_stats()
        print(f"총 기사:      {stats['total']:,}건")
        print(f"본문 보유:    {stats['has_body']:,}건")
        print(f"분석 완료:    {stats['analyzed']:,}건")
        print(f"Vector 적재:  {stats['vector_ingested']:,}건")
        return

    if args.analyze_only:
        while True:
            n = run_analysis_batch(batch_size=100)
            if n == 0:
                break
        return

    if args.vectorize_only:
        while True:
            n = run_vector_batch(batch_size=200)
            if n == 0:
                break
        return

    if args.historical:
        date_to = (
            datetime.strptime(args.date_to, "%Y-%m-%d")
            if args.date_to else datetime.now()
        )
        date_from = (
            datetime.strptime(args.date_from, "%Y-%m-%d")
            if args.date_from
            else date_to - timedelta(days=30 * args.months_back)
        )
        run_historical(
            date_from=date_from,
            date_to=date_to,
            max_items=args.max_items,
            source_only=args.source_only,
            gnews_only=args.gnews_only,
        )
    else:
        run_daily(
            max_items=args.max_items,
            source_only=args.source_only,
            gnews_only=args.gnews_only,
        )


if __name__ == "__main__":
    main()
