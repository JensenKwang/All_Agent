#!/usr/bin/env python
"""
Re-index all Postgres chunks into Qdrant semi_knowledge (BGE-M3 + Hybrid Search).

Run from project root:
    python run_reindex.py

This will:
  1. Ensure semi_knowledge collection exists in Qdrant
  2. Load BGE-M3 model (~2GB, downloaded on first run)
  3. Embed all chunks in Postgres (dense 1024d + sparse)
  4. Upsert into Qdrant with payload filters (source_type, domain, company, year)

Environment variables (optional overrides):
    INDEXER_BATCH_SIZE=16    # chunks per embed batch (increase for GPU)
    BGE_DEVICE=cpu           # or 'cuda'
    RAG_PREFETCH_LIMIT=50    # hybrid search candidates per sub-search
"""

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

log = logging.getLogger("run_reindex")

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    from app.db.qdrant import ensure_semi_knowledge, get_qdrant_client, SEMI_KNOWLEDGE_COLLECTION

    # 1. Ensure collection
    log.info("Step 1/3: Ensuring semi_knowledge collection …")
    ensure_semi_knowledge()

    # 2. Report current state
    client = get_qdrant_client()
    info = client.get_collection(SEMI_KNOWLEDGE_COLLECTION)
    log.info("Collection exists — current point count: %d", info.points_count or 0)

    # 3. Re-index
    log.info("Step 2/3: Loading BGE-M3 model (may download ~2GB on first run) …")
    from app.rag.indexer import index_all_chunks

    t0 = time.time()
    n = index_all_chunks()
    elapsed = time.time() - t0

    log.info("Step 3/3: Done. Indexed %d chunks in %.1fs (%.1f chunks/sec)", n, elapsed, n / elapsed if elapsed > 0 else 0)

    # 4. Final stats
    info2 = client.get_collection(SEMI_KNOWLEDGE_COLLECTION)
    print(f"\n{'='*50}")
    print(f"✓ semi_knowledge now has {info2.points_count} points")
    print(f"  Time: {elapsed:.1f}s  |  Rate: {n/elapsed:.1f} chunks/sec" if elapsed > 0 else "")
    print(f"{'='*50}\n")
    print("Next: test retrieval with python run_search_demo.py")
