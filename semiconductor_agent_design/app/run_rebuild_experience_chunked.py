from __future__ import annotations

import argparse
import json

from app.db.schema import ensure_postgres_schema
from app.experience import build_experience_cases_only, refresh_experience_stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Rebuild forecast experience memory in lighter chunked stages.")
    ap.add_argument("--cases-limit", type=int, default=0, help="Only rebuild the most recent evaluated cases.")
    ap.add_argument("--skip-stats", action="store_true", help="Skip the final stats refresh.")
    args = ap.parse_args()

    ensure_postgres_schema()
    case_summary = build_experience_cases_only(limit=args.cases_limit or None)
    stats_summary = {} if args.skip_stats else refresh_experience_stats()
    print(json.dumps({"cases": case_summary, "stats": stats_summary}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
