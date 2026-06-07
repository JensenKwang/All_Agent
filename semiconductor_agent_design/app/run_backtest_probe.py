from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone

from app.forecast.price_forecast import (
    _closest_close_on_or_after,
    _fetch_trade_dates,
    _forecast_for_company,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe why backtest rows may be missing.")
    parser.add_argument("--company", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--step-days", type=int, default=14)
    parser.add_argument("--horizons", default="7,14,30")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    start_dt = date.fromisoformat(args.start)
    end_dt = date.fromisoformat(args.end)
    horizons = [int(x) for x in args.horizons.split(",") if x.strip()]
    trade_dates = _fetch_trade_dates(args.company, start_dt, end_dt)

    samples: list[dict[str, object]] = []
    checked = 0
    for idx, trade_date in enumerate(trade_dates):
        if idx % max(1, args.step_days) != 0:
            continue
        as_of_dt = datetime.combine(trade_date, datetime.min.time(), tzinfo=timezone.utc)
        for horizon in horizons:
            checked += 1
            forecast = _forecast_for_company(args.company, horizon, as_of_dt)
            if forecast is None:
                samples.append(
                    {
                        "trade_date": str(trade_date),
                        "horizon": horizon,
                        "status": "forecast_none",
                    }
                )
            else:
                target_dt = date.fromisoformat(forecast.target_date)
                realized_at, realized_close = _closest_close_on_or_after(args.company, target_dt)
                samples.append(
                    {
                        "trade_date": str(trade_date),
                        "horizon": horizon,
                        "status": "ok" if realized_close is not None else "missing_realized",
                        "target_date": str(target_dt),
                        "realized_at": str(realized_at) if realized_at else None,
                        "expected_return": forecast.expected_return,
                    }
                )
            if len(samples) >= args.limit:
                break
        if len(samples) >= args.limit:
            break

    print(
        json.dumps(
            {
                "company": args.company,
                "trade_date_count": len(trade_dates),
                "checked": checked,
                "samples": samples,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
