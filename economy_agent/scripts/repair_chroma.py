"""
ChromaDB HNSW 인덱스 복구 스크립트

증상: collection.query() 결과 없음 (HNSW 인덱스 손상)
     collection.count() = 6893 (SQLite 메타데이터는 정상)

복구 흐름:
    1. SQLite FTS 테이블에서 모든 문서 + 메타데이터 추출
    2. ChromaDB 컬렉션 삭제 (HNSW 이진 파일 + SQLite 항목 모두)
    3. 컬렉션 재생성 + OpenAI 임베딩으로 재적재

실행:
    python scripts/repair_chroma.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("repair_chroma")


def extract_all_docs(db_path: str) -> list[dict]:
    """SQLite FTS + metadata에서 모든 문서를 추출합니다."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # FTS 테이블에서 rowid → 문서 텍스트
    cur.execute("SELECT rowid, c0 FROM embedding_fulltext_search_content")
    docs_map: dict[int, str] = {row[0]: row[1] for row in cur.fetchall()}
    logger.info("FTS에서 문서 추출: %d건", len(docs_map))

    # metadata 테이블에서 rowid → metadata dict
    cur.execute("SELECT id, key, string_value FROM embedding_metadata")
    meta_map: dict[int, dict[str, str]] = {}
    for row in cur.fetchall():
        rowid, key, val = row[0], row[1], row[2]
        if rowid not in meta_map:
            meta_map[rowid] = {}
        if val is not None:
            meta_map[rowid][key] = val

    # embeddings 테이블에서 공식 embedding_id 추출
    cur.execute("SELECT id, embedding_id FROM embeddings")
    id_map: dict[int, str] = {}
    for row in cur.fetchall():
        rowid = row[0]
        eid = row[1]
        # embedding_id가 bytes면 hex로 변환
        if isinstance(eid, bytes):
            eid = eid.hex()
        else:
            eid = str(eid)
        id_map[rowid] = eid

    conn.close()

    # ChromaDB 예약어 키 — metadata에서 제외해야 함
    _RESERVED = {"chroma:document", "chroma:id"}

    # 조합 — embeddings 테이블에 실제 항목이 있는 rowid만 포함 (FTS 고아 행 제외)
    records: list[dict] = []
    for rowid, eid in id_map.items():
        text = docs_map.get(rowid, "")
        text = text.strip()
        if not text or len(text) < 10:
            continue
        raw_meta = meta_map.get(rowid, {})
        meta = {k: v for k, v in raw_meta.items() if k not in _RESERVED}
        records.append({
            "id":       eid,
            "document": text,
            "metadata": meta,
        })

    logger.info("조합 완료: %d개 레코드", len(records))
    return records


def rebuild_collection(records: list[dict], batch_size: int = 100) -> None:
    """컬렉션을 삭제하고 모든 문서를 재적재합니다."""
    from macro_agent.db.vector.client import get_chroma_client, get_embedding_function, _COLLECTION_NAME

    client = get_chroma_client()
    emb_fn = get_embedding_function()

    # 컬렉션 삭제
    try:
        client.delete_collection(_COLLECTION_NAME)
        logger.info("기존 컬렉션 '%s' 삭제 완료", _COLLECTION_NAME)
    except Exception as e:
        logger.warning("컬렉션 삭제 실패 (이미 없을 수 있음): %s", e)

    # 재생성
    col = client.create_collection(
        name=_COLLECTION_NAME,
        embedding_function=emb_fn,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("컬렉션 '%s' 재생성 완료", _COLLECTION_NAME)

    # 배치 upsert
    total = len(records)
    ingested = 0
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        try:
            col.upsert(
                ids=[r["id"] for r in batch],
                documents=[r["document"] for r in batch],
                metadatas=[r["metadata"] for r in batch],
            )
            ingested += len(batch)
            logger.info("[%d/%d] 배치 upsert 완료", ingested, total)
        except Exception as exc:
            logger.error("배치 upsert 실패 (%d~%d): %s", i, i + batch_size, exc)

    final_count = col.count()
    logger.info("=== 복구 완료: %d/%d개 적재 (collection.count=%d) ===",
                ingested, total, final_count)

    # 검증 쿼리
    test_result = col.query(
        query_texts=["반도체 환율 금리"],
        n_results=3,
        include=["documents", "metadatas"],
    )
    hits = test_result["documents"][0]
    logger.info("검증 쿼리 '반도체 환율 금리' → %d건 반환", len(hits))
    for doc, meta in zip(hits, test_result["metadatas"][0]):
        logger.info("  [%s] %s: %s", meta.get("source_type"), meta.get("source_name"), doc[:60])


def main() -> None:
    parser = argparse.ArgumentParser(description="ChromaDB HNSW 인덱스 복구")
    parser.add_argument("--dry-run", action="store_true", help="실제 복구 없이 추출만 확인")
    parser.add_argument("--batch-size", type=int, default=100, help="배치 크기 (기본값: 100)")
    args = parser.parse_args()

    db_path = str(_ROOT / "data" / "chroma_db" / "chroma.sqlite3")
    logger.info("SQLite 경로: %s", db_path)

    records = extract_all_docs(db_path)
    logger.info("복구 대상: %d개 문서", len(records))

    # source_type 분포 출력
    from collections import Counter
    dist = Counter(r["metadata"].get("source_type", "unknown") for r in records)
    for st, cnt in dist.most_common():
        logger.info("  source_type=%s: %d건", st, cnt)

    if args.dry_run:
        logger.info("--dry-run 모드: 실제 복구를 건너뜁니다.")
        return

    rebuild_collection(records, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
