"""
뉴스 청크 날짜 수정용 재적재 스크립트

실행 순서:
    1. Vector DB에서 news 청크 전체 삭제 (즉시)
    2. URL 캐시 초기화 (즉시)
    3. 안내 메시지 출력 → 사용자가 historical 크롤링 재실행

사용법:
    python scripts/reingest_news.py
    # 완료 후:
    nohup python scripts/crawl_news.py --historical --months-back 12 >> logs/news_historical.log 2>&1 &
"""

import sys
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from macro_agent.db.vector.client import get_collection

_CACHE_FILE = _ROOT / "data" / "ingested_news_urls.json"


def main() -> None:
    col = get_collection()
    total_before = col.count()

    # 1. news 청크 수 확인
    news_result = col.get(where={"source_type": {"$eq": "news"}}, include=[])
    news_ids = news_result["ids"]
    news_count = len(news_ids)

    print(f"Vector DB 전체 청크: {total_before:,}개")
    print(f"삭제 대상 news 청크: {news_count:,}개")

    if news_count == 0:
        print("삭제할 news 청크가 없습니다.")
        return

    # 2. 삭제 (배치, ChromaDB는 대량 삭제 시 ID 목록이 필요)
    BATCH = 5000
    deleted = 0
    for i in range(0, len(news_ids), BATCH):
        batch_ids = news_ids[i : i + BATCH]
        col.delete(ids=batch_ids)
        deleted += len(batch_ids)
        print(f"  삭제 진행: {deleted:,}/{news_count:,}")

    total_after = col.count()
    print(f"삭제 완료 — 남은 청크: {total_after:,}개 (KCIF 리포트 등)")

    # 3. URL 캐시 초기화
    if _CACHE_FILE.exists():
        backup = _CACHE_FILE.with_suffix(".json.bak")
        _CACHE_FILE.rename(backup)
        print(f"URL 캐시 초기화 완료 (백업: {backup.name})")
    else:
        print("URL 캐시 파일 없음 — 스킵")

    print()
    print("=" * 60)
    print("다음 명령어로 뉴스를 재적재하세요:")
    print()
    print("  nohup python scripts/crawl_news.py --historical --months-back 12 \\")
    print("    >> logs/news_historical.log 2>&1 &")
    print()
    print("진행 확인:")
    print("  tail -f logs/news_historical.log")
    print("=" * 60)


if __name__ == "__main__":
    main()
