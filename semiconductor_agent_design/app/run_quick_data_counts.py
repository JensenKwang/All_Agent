from __future__ import annotations

import json

from app.db.postgres import get_pg_conn


def main() -> None:
    payload: dict[str, object] = {}
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            for table in [
                "tech_documents",
                "tech_document_chunks",
                "paper_sections",
                "paper_tables",
                "paper_figures",
                "event_candidates",
                "event_outcomes",
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                payload[table] = int(cur.fetchone()[0])

            cur.execute(
                """
                SELECT source, COUNT(*)
                FROM tech_documents
                GROUP BY source
                ORDER BY COUNT(*) DESC
                LIMIT 10
                """
            )
            payload["top_sources"] = cur.fetchall()

    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
