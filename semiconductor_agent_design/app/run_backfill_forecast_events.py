from __future__ import annotations

import argparse
import json
from typing import Any

from app.db.postgres import get_pg_conn
from app.forecast.price_forecast import (
    _coerce_json_dict,
    _normalize_stored_forecast_payloads,
    enrich_signals_with_normalized_event,
)


def backfill_forecast_events(limit: int | None = None, force: bool = False) -> dict[str, Any]:
    sql = """
        SELECT
          f.id,
          f.company_code,
          f.as_of,
          f.signals,
          f.features,
          f.scenarios,
          f.low_return,
          f.high_return,
          e.extra
        FROM price_forecasts f
        LEFT JOIN price_forecast_evaluations e ON e.forecast_id = f.id
        ORDER BY f.as_of DESC
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))

    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    seen = 0
    updated = 0
    skipped = 0
    without_event = 0

    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            for (
                forecast_id,
                company_code,
                as_of,
                signals_raw,
                features_raw,
                scenarios_raw,
                low_return,
                high_return,
                eval_extra_raw,
            ) in rows or []:
                seen += 1
                scenarios, features, signals = _normalize_stored_forecast_payloads(
                    scenarios_raw,
                    features_raw,
                    signals_raw,
                )
                enriched_signals = enrich_signals_with_normalized_event(company_code, as_of, signals)
                has_event = bool((enriched_signals or {}).get("normalized_event"))
                if not has_event:
                    without_event += 1
                if not force and enriched_signals == signals:
                    skipped += 1
                    continue

                cur.execute(
                    """
                    UPDATE price_forecasts
                    SET signals = %s::jsonb,
                        features = %s::jsonb,
                        scenarios = %s::jsonb
                    WHERE id = %s
                    """,
                    (
                        json.dumps(enriched_signals, ensure_ascii=False),
                        json.dumps(features, ensure_ascii=False),
                        json.dumps(scenarios, ensure_ascii=False),
                        forecast_id,
                    ),
                )

                eval_extra = _coerce_json_dict(eval_extra_raw)
                if eval_extra_raw is not None:
                    eval_extra["signals"] = enriched_signals
                    if features:
                        eval_extra["features"] = features
                    if low_return is not None:
                        eval_extra["low_return"] = float(low_return)
                    if high_return is not None:
                        eval_extra["high_return"] = float(high_return)
                    cur.execute(
                        """
                        UPDATE price_forecast_evaluations
                        SET extra = %s::jsonb
                        WHERE forecast_id = %s
                        """,
                        (json.dumps(eval_extra, ensure_ascii=False), forecast_id),
                    )

                updated += 1
        conn.commit()

    return {
        "seen": seen,
        "updated": updated,
        "skipped": skipped,
        "without_event": without_event,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill normalized semiconductor event metadata into stored forecasts.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    result = backfill_forecast_events(limit=args.limit, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
