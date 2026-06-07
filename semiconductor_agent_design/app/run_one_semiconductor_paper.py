import argparse
import logging

from app.collectors.paper_collector import ingest_top_arxiv_by_query


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Search arXiv by semiconductor query and ingest one selected paper."
    )
    parser.add_argument(
        "--query",
        default='(all:HBM OR all:DRAM OR all:NAND) AND (all:semiconductor OR all:packaging OR all:TSV)',
        help="arXiv search query",
    )
    parser.add_argument("--index", type=int, default=0, help="picked paper index from search result")
    parser.add_argument("--max-results", type=int, default=10, help="number of papers to fetch from arXiv query")
    parser.add_argument("--query-id", default="semiconductor_auto", help="metadata tag")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    result = ingest_top_arxiv_by_query(
        query_text=args.query,
        query_id=args.query_id,
        pick_index=args.index,
        max_results=args.max_results,
    )
    print("[OK] One semiconductor paper ingestion complete")
    print(result)


if __name__ == "__main__":
    main()
