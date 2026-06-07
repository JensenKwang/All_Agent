from __future__ import annotations

import json

from app.collectors.market_collector import collect_global_stock_prices, collect_krx_daily
from app.db.postgres import get_pg_conn
from app.db.schema import ensure_postgres_schema


TARGETS = ("005930", "000660", "042700", "NVDA", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MU", "INTC", "AMD")


def _fetch_ranges() -> list[dict[str, object]]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT company_code, MIN(trade_date), MAX(trade_date), COUNT(*)
                FROM price_daily
                WHERE company_code = ANY(%s)
                GROUP BY company_code
                ORDER BY company_code
                """,
                (list(TARGETS),),
            )
            rows = cur.fetchall()
    return [
        {
            "company_code": code,
            "min_trade_date": str(min_dt),
            "max_trade_date": str(max_dt),
            "row_count": int(count),
        }
        for code, min_dt, max_dt, count in rows or []
    ]


def main() -> None:
    ensure_postgres_schema()
    before = _fetch_ranges()
    collect_krx_daily()
    collect_global_stock_prices()
    after = _fetch_ranges()
    print(
        json.dumps(
            {
                "before": before,
                "after": after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
