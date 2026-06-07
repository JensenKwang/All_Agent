from __future__ import annotations

import argparse
import json
from typing import Any

from app.agent.semiconductor_event_utils import classify_event_type, classify_technology_category
from app.db.postgres import get_pg_conn


GENERIC_TYPES = {"paper", "company_official", "rss_news", "tech_blog", "conference_metadata", "event_candidate"}


def backfill_event_candidate_types(limit: int | None = None, force: bool = False) -> dict[str, Any]:
    sql = """
        SELECT event_id, title, summary, related_domain, event_type, extra
        FROM event_candidates
        ORDER BY event_date DESC
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT %s"
        params.append(int(limit))

    updated = 0
    skipped = 0
    seen = 0
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            for event_id, title, summary, related_domain, event_type, extra in rows or []:
                seen += 1
                current = str(event_type or "").strip()
                inferred = classify_event_type(f"{title or ''} {summary or ''}", str(related_domain or ""))
                extra_d = dict(extra or {})
                tech_category = classify_technology_category(f"{title or ''} {summary or ''}", str(related_domain or ""))
                extra_changed = extra_d.get("technology_category") != tech_category
                if not force and current not in GENERIC_TYPES and current == inferred:
                    if not extra_changed:
                        skipped += 1
                        continue
                if not force and current == inferred and not extra_changed:
                    skipped += 1
                    continue
                extra_d["technology_category"] = tech_category
                cur.execute(
                    """
                    UPDATE event_candidates
                    SET event_type = %s,
                        extra = %s::jsonb
                    WHERE event_id = %s
                    """,
                    (inferred, json.dumps(extra_d, ensure_ascii=False), event_id),
                )
                updated += 1
        conn.commit()
    return {"seen": seen, "updated": updated, "skipped": skipped}


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill semantic event_type values for event_candidates.")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    print(json.dumps(backfill_event_candidate_types(limit=args.limit, force=args.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
