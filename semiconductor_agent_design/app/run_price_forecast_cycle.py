from __future__ import annotations

import argparse
import json
import logging

from app.db.schema import ensure_postgres_schema
from app.experience import build_forecast_experience_memory
from app.forecast.price_forecast import (
    DEFAULT_COMPANIES,
    DEFAULT_HORIZONS,
    backtest_price_forecasts,
    evaluate_due_forecasts,
    generate_price_forecasts,
    render_backtest_summary_markdown,
    render_forecast_summary,
)


def _parse_list(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def _parse_int_list(value: str) -> list[int]:
    out: list[int] = []
    for part in _parse_list(value):
        try:
            out.append(int(part))
        except Exception:
            continue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and evaluate scenario-based price forecasts.")
    parser.add_argument("--companies", default=",".join(DEFAULT_COMPANIES))
    parser.add_argument("--horizons", default=",".join(str(x) for x in DEFAULT_HORIZONS))
    parser.add_argument("--evaluate-only", action="store_true")
    parser.add_argument("--as-of", default="")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--backtest-start", default="")
    parser.add_argument("--backtest-end", default="")
    parser.add_argument("--backtest-step-days", default="7")
    parser.add_argument("--skip-experience", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    ensure_postgres_schema()

    forecasts = []
    if not args.evaluate_only:
        forecasts = generate_price_forecasts(
            company_codes=_parse_list(args.companies),
            horizons=_parse_int_list(args.horizons),
            as_of=args.as_of or None,
        )

    evaluations = evaluate_due_forecasts()
    backtest = None
    if args.backtest:
        backtest = backtest_price_forecasts(
            company_codes=_parse_list(args.companies),
            horizons=_parse_int_list(args.horizons),
            start_date=args.backtest_start or None,
            end_date=args.backtest_end or None,
            step_days=int(args.backtest_step_days),
        )
    experience = None
    if not args.skip_experience:
        experience = build_forecast_experience_memory()

    if args.json:
        print(
            json.dumps(
                {
                    "forecasts": forecasts,
                    "evaluations": evaluations,
                    "backtest": backtest,
                    "experience": experience,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    print("[FORECASTS]")
    print(render_forecast_summary(forecasts))
    print()
    print("[EVALUATIONS]")
    print(json.dumps(evaluations, ensure_ascii=False, indent=2))
    if backtest is not None:
        print()
        print("[BACKTEST]")
        print(render_backtest_summary_markdown(backtest))
        print()
        print(json.dumps(backtest, ensure_ascii=False, indent=2))
    if experience is not None:
        print()
        print("[EXPERIENCE]")
        print(json.dumps(experience, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
