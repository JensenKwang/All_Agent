from __future__ import annotations

import json

from app.db.postgres import get_pg_conn


def _fetchall(sql: str) -> list[tuple]:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return list(cur.fetchall() or [])


def fetch_report() -> dict[str, object]:
    return {
        "case_count": _fetchall("SELECT COUNT(*) FROM forecast_experience_cases")[0][0],
        "success_labels": _fetchall(
            """
            SELECT success_label, COUNT(*)
            FROM forecast_experience_cases
            GROUP BY success_label
            ORDER BY COUNT(*) DESC
            """
        ),
        "primary_patterns": _fetchall(
            """
            SELECT primary_pattern, COUNT(*)
            FROM forecast_experience_cases
            WHERE primary_pattern IS NOT NULL AND primary_pattern != ''
            GROUP BY primary_pattern
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """
        ),
        "error_tag_counts": _fetchall(
            """
            SELECT tag, COUNT(*)
            FROM (
              SELECT unnest(error_tags) AS tag
              FROM forecast_experience_cases
            ) t
            GROUP BY tag
            ORDER BY COUNT(*) DESC, tag ASC
            """
        ),
        "by_company": _fetchall(
            """
            SELECT company_code, COUNT(*)
            FROM forecast_experience_cases
            GROUP BY company_code
            ORDER BY COUNT(*) DESC
            """
        ),
        "by_horizon": _fetchall(
            """
            SELECT horizon_days, COUNT(*)
            FROM forecast_experience_cases
            GROUP BY horizon_days
            ORDER BY horizon_days
            """
        ),
        "by_domain": _fetchall(
            """
            SELECT related_domain, COUNT(*)
            FROM forecast_experience_cases
            WHERE related_domain IS NOT NULL AND related_domain != ''
            GROUP BY related_domain
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """
        ),
        "by_event_type": _fetchall(
            """
            SELECT context->>'event_type' AS event_type, COUNT(*)
            FROM forecast_experience_cases
            WHERE COALESCE(context->>'event_type', '') != ''
            GROUP BY context->>'event_type'
            ORDER BY COUNT(*) DESC
            LIMIT 12
            """
        ),
    }


def main() -> None:
    payload = fetch_report()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
