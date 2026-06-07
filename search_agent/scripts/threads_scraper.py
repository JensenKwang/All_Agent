"""
threads_scraper.py
Scrapfly SDK를 이용한 Threads 트렌드 키워드 포스트 크롤링.
KoBERT fine-tuning용 반도체 감성 분석 데이터 수집.

사용법:
    python threads_scraper.py
    from threads_scraper import run_scraper
"""

import os
import json
import time
import re
from datetime import datetime
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

SCRAPFLY_API_KEY = os.getenv("SCRAPFLY_API_KEY", "")
KOBERT_DATA_FILE = "threads_kobert_data.jsonl"
MIN_TEXT_LENGTH = 20  # 최소 텍스트 길이

SEARCH_KEYWORDS = [
    "반도체", "HBM", "TSMC", "삼성전자파운드리",
    "SK하이닉스", "AI반도체", "엔비디아",
]

# Threads HTML 파싱 셀렉터 (변경될 수 있음)
POST_SELECTORS = [
    "article[data-testid]",
    "div[role='article']",
    "div[data-pressable-container]",
]
TEXT_SELECTORS = [
    "[data-testid='post-text']",
    "span.x1lliihq",
    "div[dir='auto'] span",
]

try:
    from scrapfly import ScrapflyClient, ScrapeConfig
    SCRAPFLY_AVAILABLE = True
except ImportError:
    SCRAPFLY_AVAILABLE = False


class ThreadsScraper:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or SCRAPFLY_API_KEY
        if not self.api_key:
            raise ValueError("[Scrapfly] SCRAPFLY_API_KEY가 .env에 설정되어 있지 않습니다.")
        if not SCRAPFLY_AVAILABLE:
            raise ImportError("scrapfly-sdk가 설치되어 있지 않습니다. pip install scrapfly-sdk")
        self.client = ScrapflyClient(key=self.api_key)

    def _scrape_url(self, url: str, render_js: bool = True) -> str | None:
        """Scrapfly로 단일 URL 크롤링."""
        try:
            config = ScrapeConfig(
                url=url,
                asp=True,
                render_js=render_js,
                country="KR",
                headers={"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"},
                timeout=30000,
            )
            result = self.client.scrape(config)
            return result.content
        except Exception as e:
            print(f"[Scrapfly] 크롤링 실패 ({url[:60]}...): {e}")
            return None

    def _parse_posts_from_html(self, html: str, keyword: str) -> list[dict]:
        """BeautifulSoup으로 Threads 검색 결과 포스트 텍스트 파싱."""
        posts = []
        soup = BeautifulSoup(html, "html.parser")
        collected_at = datetime.now().strftime("%Y-%m-%d")

        # 셀렉터 순서대로 시도
        post_elements = []
        for selector in POST_SELECTORS:
            post_elements = soup.select(selector)
            if post_elements:
                break

        if post_elements:
            for elem in post_elements:
                text = ""
                for text_sel in TEXT_SELECTORS:
                    text_elem = elem.select_one(text_sel)
                    if text_elem:
                        text = text_elem.get_text(strip=True)
                        break
                if not text:
                    # 텍스트 셀렉터 실패 시 elem 전체 텍스트 사용
                    text = elem.get_text(separator=" ", strip=True)

                if len(text) >= MIN_TEXT_LENGTH:
                    posts.append({
                        "text": text,
                        "keyword": keyword,
                        "source": "threads",
                        "collected_at": collected_at,
                    })
        else:
            # 셀렉터 전부 실패 → regex fallback
            # 한국어 포함 20자 이상 텍스트 블록 추출
            raw_text = soup.get_text(separator="\n")
            lines = raw_text.split("\n")
            for line in lines:
                line = line.strip()
                if len(line) >= MIN_TEXT_LENGTH and keyword in line:
                    posts.append({
                        "text": line,
                        "keyword": keyword,
                        "source": "threads",
                        "collected_at": collected_at,
                    })

        return posts

    def scrape_keyword_posts(self, keyword: str, max_posts: int = 50) -> list[dict]:
        """특정 키워드로 Threads 검색 결과 포스트 수집."""
        from urllib.parse import quote
        url = f"https://www.threads.net/search?q={quote(keyword)}&serp_type=default"
        print(f"[Scrapfly] '{keyword}' 크롤링 중...")

        # 1차 시도: render_js=False (크레딧 절약)
        html = self._scrape_url(url, render_js=False)
        if html:
            posts = self._parse_posts_from_html(html, keyword)
            if posts:
                print(f"[Scrapfly] '{keyword}': {len(posts)}건 수집 (정적 렌더링)")
                return posts[:max_posts]

        # 2차 시도: render_js=True (동적 렌더링)
        html = self._scrape_url(url, render_js=True)
        if html:
            posts = self._parse_posts_from_html(html, keyword)
            print(f"[Scrapfly] '{keyword}': {len(posts)}건 수집 (동적 렌더링)")
            return posts[:max_posts]

        return []

    def scrape_all_keywords(self, keywords: list[str] = None) -> list[dict]:
        """전체 키워드 순회 크롤링."""
        targets = keywords or SEARCH_KEYWORDS
        all_posts = []
        for kw in targets:
            posts = self.scrape_keyword_posts(kw)
            all_posts.extend(posts)
            time.sleep(2)  # rate limit 방지
        return all_posts


def save_for_kobert(posts: list[dict], filepath: str = KOBERT_DATA_FILE) -> int:
    """
    KoBERT 학습용 JSONL 형식으로 저장.
    중복 텍스트 제거, 최소 길이 필터링 후 append.
    """
    # 기존 텍스트 로드 (중복 제거용)
    existing_texts = set()
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    existing_texts.add(obj.get("text", ""))
                except Exception:
                    pass

    saved = 0
    with open(filepath, "a", encoding="utf-8") as f:
        for post in posts:
            text = post.get("text", "").strip()
            if len(text) < MIN_TEXT_LENGTH:
                continue
            if text in existing_texts:
                continue
            existing_texts.add(text)
            f.write(json.dumps(post, ensure_ascii=False) + "\n")
            saved += 1

    print(f"[Scrapfly] KoBERT 데이터 {saved}건 저장 → {filepath}")
    return saved


def run_scraper(api_key: str = None) -> None:
    """main.py에서 호출하는 진입점 함수."""
    if not SCRAPFLY_AVAILABLE:
        print("[Scrapfly] scrapfly-sdk 미설치 → 크롤링 스킵")
        print("  설치: pip install scrapfly-sdk")
        return

    key = api_key or SCRAPFLY_API_KEY
    if not key:
        print("[Scrapfly] SCRAPFLY_API_KEY 미설정 → 크롤링 스킵")
        return

    try:
        scraper = ThreadsScraper(api_key=key)
        posts = scraper.scrape_all_keywords()
        if posts:
            save_for_kobert(posts)
        else:
            print("[Scrapfly] 수집된 포스트 없음")
    except Exception as e:
        print(f"[Scrapfly] 오류: {e}")


if __name__ == "__main__":
    run_scraper()
