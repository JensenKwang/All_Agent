import argparse
import logging

from app.collectors.paper_collector import ingest_batch_arxiv_by_query


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch ingest semiconductor-focused papers from arXiv.")
    parser.add_argument(
        "--query",
        default='(all:HBM OR all:DRAM OR all:NAND OR all:TSV OR all:"hybrid bonding" OR all:FinFET OR all:GAA OR all:EUV) AND (all:semiconductor OR all:foundry OR all:wafer OR all:fabrication OR all:packaging)',
        help="arXiv query string",
    )
    parser.add_argument("--max-results", type=int, default=50, help="number of candidate papers to fetch")
    parser.add_argument("--ingest-limit", type=int, default=12, help="max papers to ingest in this run")
    parser.add_argument("--query-id", default="semiconductor_batch", help="metadata tag")
    parser.add_argument("--year-min", type=int, default=None, help="min publication year (inclusive)")
    parser.add_argument("--year-max", type=int, default=None, help="max publication year (inclusive)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    summary = ingest_batch_arxiv_by_query(
        query_text=args.query,
        query_id=args.query_id,
        max_results=args.max_results,
        ingest_limit=args.ingest_limit,
        year_min=args.year_min,
        year_max=args.year_max,
    )

    print("[OK] Semiconductor batch ingestion complete")
    print(
        f"fetched={summary['fetched']} year_filtered_out={summary['year_filtered_out']} "
        f"year_min={summary['year_min']} year_max={summary['year_max']} accepted={summary['accepted']} "
        f"ingested={summary['ingested']} failed={summary['failed']} rejected={summary['rejected']} "
        f"limit={summary['limit']}"
    )


if __name__ == "__main__":
    main()
