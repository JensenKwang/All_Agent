import logging

from app.db.schema import ensure_postgres_schema
from app.events.builder import build_event_dataset


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    ensure_postgres_schema()
    result = build_event_dataset()
    print("[OK] Event dataset build complete")
    print(result)


if __name__ == "__main__":
    main()
