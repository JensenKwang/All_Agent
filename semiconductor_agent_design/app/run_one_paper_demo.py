import argparse
import logging

from app.collectors.paper_collector import ingest_single_arxiv_paper


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest one arXiv paper (PDF -> text -> chunks -> sections/tables/figures).")
    parser.add_argument("--arxiv", required=True, help="arXiv abs URL or ID. e.g. https://arxiv.org/abs/2401.12345")
    parser.add_argument("--query-id", default="manual_demo", help="Tag to store in metadata")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    result = ingest_single_arxiv_paper(args.arxiv, query_id=args.query_id)
    print("[OK] One paper ingestion complete")
    print(result)


if __name__ == "__main__":
    main()
