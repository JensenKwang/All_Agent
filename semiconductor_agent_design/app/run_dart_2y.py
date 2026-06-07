import logging

from app.collectors.dart_collector import collect_dart_new_filings, collect_dart_quarterly


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    # 2-year filings backfill + quarterly financial extraction
    collect_dart_new_filings(lookback_days=730)
    collect_dart_quarterly()
    print("[OK] Open DART 2-year backfill complete")


if __name__ == "__main__":
    main()
