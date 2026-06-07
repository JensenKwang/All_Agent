#!/usr/bin/env python
"""
Hybrid search demo — run after run_reindex.py completes.

Tests:
  1. General semiconductor query
  2. HBM-specific paper search
  3. Samsung-filtered query
  4. Multi-query fusion
  5. LLM context builder

Usage:
    python run_search_demo.py
    python run_search_demo.py "your custom query here"
"""

import logging
import sys

logging.basicConfig(
    level=logging.WARNING,  # suppress model noise
    format="%(asctime)s | %(levelname)s | %(message)s",
)

from dotenv import load_dotenv
load_dotenv()


def print_results(results: list[dict], label: str, n: int = 5) -> None:
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    for i, r in enumerate(results[:n], 1):
        score = r.get("score", 0)
        title = r.get("title", "")[:70]
        src   = r.get("source", "")
        year  = r.get("year", "")
        dom   = r.get("domain", "")
        text  = r.get("text", "")[:200].replace("\n", " ")
        print(f"[{i}] score={score:.4f}  domain={dom}  source={src}  year={year}")
        print(f"    {title}")
        print(f"    {text}")
    if not results:
        print("  (no results — collection may be empty, run run_reindex.py first)")


def main():
    from app.rag.retriever import search, search_multi_query, get_context_for_llm
    from app.db.qdrant import get_qdrant_client, SEMI_KNOWLEDGE_COLLECTION

    # Check collection size
    client = get_qdrant_client()
    info = client.get_collection(SEMI_KNOWLEDGE_COLLECTION)
    print(f"\n✓ semi_knowledge: {info.points_count} points")

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        results = search(query, top_k=10)
        print_results(results, f'Query: "{query}"')
        return

    # --- Test 1: General ---
    r1 = search("HBM3 memory thermal resistance copper pillar bonding", top_k=5)
    print_results(r1, "① HBM3 thermal (general)")

    # --- Test 2: Papers only ---
    r2 = search("3D NAND flash endurance retention degradation", top_k=5, filter_source_type="paper")
    print_results(r2, "② 3D NAND papers only")

    # --- Test 3: Company filter ---
    r3 = search("advanced packaging chiplet interposer", top_k=5, filter_company="005930")
    print_results(r3, "③ Samsung (005930) packaging")

    # --- Test 4: Domain filter ---
    r4 = search("EUV extreme ultraviolet stochastic defect overlay", top_k=5, filter_domain="litho")
    print_results(r4, "④ EUV litho domain filter")

    # --- Test 5: Multi-query ---
    queries = [
        "HBM bandwidth memory bandwidth per pin",
        "HBM thermal design power cooling",
        "HBM3E CoWoS integration yield",
    ]
    r5 = search_multi_query(queries, top_k=5)
    print_results(r5, "⑤ Multi-query HBM fusion")

    # --- Test 6: LLM context ---
    context = get_context_for_llm(
        "SK Hynix HBM3E packaging technology competitive advantage",
        top_k=5,
        max_chars=3000,
        filter_company="000660",
    )
    print(f"\n{'─'*60}")
    print("  ⑥ LLM Context block (SK Hynix HBM3E)")
    print(f"{'─'*60}")
    print(context[:1500] or "(empty)")


if __name__ == "__main__":
    main()
