from __future__ import annotations

import argparse
import json

from app.experience import backfill_experience_event_types


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill event_type into existing forecast experience cases.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on rows to patch.")
    args = parser.parse_args()

    payload = backfill_experience_event_types(limit=args.limit or None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
