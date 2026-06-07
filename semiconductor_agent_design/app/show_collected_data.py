from app.db.postgres import get_pg_conn


def print_section(title: str) -> None:
    print("\n" + "=" * 90)
    print(title)
    print("=" * 90)


def show_disclosures(limit: int = 20) -> None:
    print_section(f"Latest Disclosures (top {limit})")
    sql = """
    SELECT company_code, rcept_no, report_type, title, published_at
    FROM disclosures
    ORDER BY published_at DESC
    LIMIT %s
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    if not rows:
        print("No rows.")
        return
    for r in rows:
        print(f"company={r[0]} | rcept_no={r[1]} | type={r[2]} | published_at={r[4]} | title={r[3]}")


def show_metrics(limit: int = 30) -> None:
    print_section(f"Latest Metric Observations (top {limit})")
    sql = """
    SELECT company_code, metric_name, metric_value, unit, published_at, prov_entity
    FROM metric_observations
    ORDER BY published_at DESC
    LIMIT %s
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    if not rows:
        print("No rows.")
        return
    for r in rows:
        print(
            f"company={r[0]} | metric={r[1]} | value={r[2]} {r[3]} | published_at={r[4]} | prov={r[5]}"
        )


def show_metric_summary() -> None:
    print_section("Metric Summary by Company and Metric")
    sql = """
    SELECT company_code, metric_name, COUNT(*) AS cnt, MAX(published_at) AS latest_ts
    FROM metric_observations
    GROUP BY company_code, metric_name
    ORDER BY company_code, metric_name
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    if not rows:
        print("No rows.")
        return
    for r in rows:
        print(f"company={r[0]} | metric={r[1]} | count={r[2]} | latest={r[3]}")


def show_tech_documents(limit: int = 30) -> None:
    print_section(f"Latest Tech Documents (top {limit})")
    sql = """
    SELECT source, source_type, title, url, published_at, tags, confidence
    FROM tech_documents
    ORDER BY collected_at DESC
    LIMIT %s
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    if not rows:
        print("No rows.")
        return
    for r in rows:
        print(
            f"source={r[0]} | type={r[1]} | published_at={r[4]} | confidence={r[6]} | tags={r[5]} | title={r[2]} | url={r[3]}"
        )


def show_paper_chunk_summary(limit: int = 20) -> None:
    print_section(f"Paper Chunk Summary (top {limit})")
    sql = """
    SELECT d.source, d.title, d.url, COUNT(c.id) AS chunk_count, MAX(c.created_at) AS last_chunked_at
    FROM tech_documents d
    LEFT JOIN tech_document_chunks c ON d.doc_uid = c.doc_uid
    WHERE d.source_type = 'paper'
    GROUP BY d.doc_uid, d.source, d.title, d.url
    ORDER BY chunk_count DESC, last_chunked_at DESC NULLS LAST
    LIMIT %s
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    if not rows:
        print("No rows.")
        return
    for r in rows:
        print(f"source={r[0]} | chunks={r[3]} | last_chunked_at={r[4]} | title={r[1]} | url={r[2]}")


def show_paper_structure_summary(limit: int = 20) -> None:
    print_section(f"Paper Structure Summary (top {limit})")
    sql = """
    SELECT d.title,
           d.url,
           COALESCE(sec.cnt, 0) AS section_count,
           COALESCE(tbl.cnt, 0) AS table_count,
           COALESCE(fig.cnt, 0) AS figure_count
    FROM tech_documents d
    LEFT JOIN (
      SELECT doc_uid, COUNT(*) AS cnt FROM paper_sections GROUP BY doc_uid
    ) sec ON d.doc_uid = sec.doc_uid
    LEFT JOIN (
      SELECT doc_uid, COUNT(*) AS cnt FROM paper_tables GROUP BY doc_uid
    ) tbl ON d.doc_uid = tbl.doc_uid
    LEFT JOIN (
      SELECT doc_uid, COUNT(*) AS cnt FROM paper_figures GROUP BY doc_uid
    ) fig ON d.doc_uid = fig.doc_uid
    WHERE d.source_type = 'paper'
    ORDER BY section_count DESC, table_count DESC, figure_count DESC
    LIMIT %s
    """
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
    if not rows:
        print("No rows.")
        return
    for r in rows:
        print(
            f"sections={r[2]} | tables={r[3]} | figures={r[4]} | title={r[0]} | url={r[1]}"
        )


def main() -> None:
    show_disclosures()
    show_metrics()
    show_metric_summary()
    show_tech_documents()
    show_paper_chunk_summary()
    show_paper_structure_summary()


if __name__ == "__main__":
    main()
