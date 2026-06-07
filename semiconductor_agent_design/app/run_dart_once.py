import logging

from app.collectors.dart_collector import collect_dart_new_filings, collect_dart_quarterly


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    collect_dart_new_filings()
    collect_dart_quarterly()
    print("[OK] Open DART one-shot run complete")


if __name__ == "__main__":
    main()
