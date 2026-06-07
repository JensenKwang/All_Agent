from __future__ import annotations

import argparse
import json

from app.db.schema import ensure_postgres_schema
from app.experience import build_forecast_experience_memory, find_similar_experience_cases, get_experience_profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Build experience-memory tables from forecast backtests.")
    parser.add_argument("--limit", type=int, default=0, help="Optional limit on evaluated cases to scan.")
    parser.add_argument("--company", default="", help="Optional company code to preview profile/cases.")
    parser.add_argument("--horizon", type=int, default=0, help="Optional horizon to preview profile/cases.")
    parser.add_argument("--domain", default="", help="Optional related domain to preview profile/cases.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    ensure_postgres_schema()
    summary = build_forecast_experience_memory(limit=args.limit or None)

    preview: dict[str, object] = {}
    if args.company and args.horizon:
        preview["profile"] = get_experience_profile(
            company_code=args.company,
            horizon_days=args.horizon,
            related_domain=args.domain or None,
            stat_group="company_horizon",
        )
        preview["similar_cases"] = find_similar_experience_cases(
            company_code=args.company,
            horizon_days=args.horizon,
            related_domain=args.domain or None,
            limit=5,
        )

    payload = {
        "summary": summary,
        "preview": preview,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return

    print("[EXPERIENCE_MEMORY]")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
