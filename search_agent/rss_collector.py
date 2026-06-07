import feedparser
import requests
from datetime import datetime

# 주요 한국 언론사 RSS 피드 목록 (동작 확인된 URL만)
RSS_SOURCES = {
    "연합뉴스":  "https://www.yna.co.kr/rss/news.xml",
    "한겨레":    "https://www.hani.co.kr/rss/",
    "MBC뉴스":  "https://imnews.imbc.com/rss/google_news/narrativeNews.rss",
    "SBS뉴스":  "https://news.sbs.co.kr/news/headlineRssFeed.do?plink=RSSREADER",
    "경향신문":  "https://www.khan.co.kr/rss/rssdata/total_news.xml",
    "한국경제":  "https://www.hankyung.com/feed/all-news",
    "조선일보":  "https://www.chosun.com/arc/outboundfeeds/rss/?outputType=xml",
    "동아일보":  "https://rss.donga.com/total.xml",
    "매일경제":  "https://www.mk.co.kr/rss/40300001/",
    "전자신문":  "https://www.etnews.com/etnews/rss.xml",
    "디지털타임스": "https://www.dt.co.kr/rss/rss.xml",
    "이데일리":  "https://rss.edaily.co.kr/edaily_allnews.xml",
    "아시아경제": "https://rss.asiae.co.kr/news/rss.htm",
    "서울경제":  "https://www.sedaily.com/RSS/V",
    "뉴시스":   "https://www.newsis.com/RSS/",
}

def parse_date(entry):
    """feedparser entry에서 날짜를 YYYY-MM-DD HH:mm:ss 형태로 변환."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6])
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    return entry.get("published", "")

def fetch_rss_news(query=None, sources=None, display=10):
    """
    RSS 피드에서 뉴스를 수집합니다.

    Args:
        query (str|None): 키워드 필터 (None이면 전체 수집)
        sources (dict|None): {'언론사명': 'RSS URL'} 형태. None이면 기본 RSS_SOURCES 사용.
        display (int): 언론사당 최대 수집 건수

    Returns:
        list: [{'title', 'press', 'url', 'pub_date', 'description'}, ...]
    """
    if sources is None:
        sources = RSS_SOURCES

    results = []

    for press_name, rss_url in sources.items():
        try:
            resp = requests.get(rss_url, timeout=(5, 10), headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(resp.content)
            count = 0

            for entry in feed.entries:
                if count >= display:
                    break

                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                description = entry.get("summary", "").strip()
                pub_date = parse_date(entry)

                if not title or not url:
                    continue

                # 키워드 필터 (제목 또는 요약에 포함 여부)
                if query and query not in title and query not in description:
                    continue

                results.append({
                    "title": title,
                    "press": press_name,
                    "url": url,
                    "pub_date": pub_date,
                    "description": description,
                    "source_type": "rss_naver",
                })
                count += 1

            print(f"[RSS] {press_name}: {count}건 수집")

        except Exception as e:
            print(f"[RSS] {press_name} 피드 오류: {e}")

    return results


GOOGLE_NEWS_QUERIES = [
    "반도체", "삼성전자", "SK하이닉스", "HBM", "파운드리",
    "엔비디아", "TSMC", "AI반도체", "메모리반도체", "시스템반도체"
]

def fetch_google_news_rss(queries=None, display=20):
    """
    구글 뉴스 RSS에서 키워드별 뉴스를 수집합니다.

    Args:
        queries (list|None): 검색 키워드 리스트. None이면 기본 GOOGLE_NEWS_QUERIES 사용.
        display (int): 키워드당 최대 수집 건수

    Returns:
        list: [{'title', 'press', 'url', 'pub_date', 'description'}, ...]
    """
    if queries is None:
        queries = GOOGLE_NEWS_QUERIES

    results = []

    for query in queries:
        try:
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
            resp = requests.get(rss_url, timeout=(5, 10), headers={"User-Agent": "Mozilla/5.0"})
            feed = feedparser.parse(resp.content)
            count = 0

            for entry in feed.entries:
                if count >= display:
                    break

                title = entry.get("title", "").strip()
                url = entry.get("link", "").strip()
                description = entry.get("summary", "").strip()
                pub_date = parse_date(entry)

                # 구글 뉴스는 source.title에 언론사명이 있음
                press = "알 수 없음"
                if hasattr(entry, "source") and hasattr(entry.source, "title"):
                    press = entry.source.title

                if not title or not url:
                    continue

                results.append({
                    "title": title,
                    "press": press,
                    "url": url,
                    "pub_date": pub_date,
                    "description": description,
                    "source_type": "rss_google",
                })
                count += 1

            print(f"[Google News RSS] '{query}': {count}건 수집")

        except Exception as e:
            print(f"[Google News RSS] '{query}' 오류: {e}")

    return results


if __name__ == "__main__":
    query = "인공지능"
    print(f"'{query}' 키워드로 RSS 뉴스 수집 테스트...\n")
    news_list = fetch_rss_news(query=query, display=5)
    print(f"\n총 {len(news_list)}건 수집됨\n")
    for i, news in enumerate(news_list, 1):
        print(f"[{i}] [{news['press']}] {news['title']}")
        print(f"    - 게시일: {news['pub_date']}")
        print(f"    - URL: {news['url']}\n")
