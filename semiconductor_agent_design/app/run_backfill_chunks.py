import argparse

from app.rag.backfill_chunks import backfill_document_summary_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill searchable chunks from document summaries.")
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    inserted = backfill_document_summary_chunks(limit=args.limit)
    print(f"[OK] backfilled_chunks={inserted}")


if __name__ == "__main__":
    main()
