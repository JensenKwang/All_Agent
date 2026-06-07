import argparse

from app.db.postgres import get_pg_conn


def _resolve_doc_uid(ref: str) -> str | None:
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            if ref.startswith("http://") or ref.startswith("https://"):
                cur.execute(
                    "SELECT doc_uid FROM tech_documents WHERE url=%s ORDER BY collected_at DESC LIMIT 1",
                    (ref,),
                )
            else:
                cur.execute(
                    "SELECT doc_uid FROM tech_documents WHERE doc_uid=%s LIMIT 1",
                    (ref,),
                )
            row = cur.fetchone()
    return row[0] if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Show detailed structure of one ingested paper.")
    parser.add_argument("--ref", required=True, help="doc_uid or paper URL")
    args = parser.parse_args()

    doc_uid = _resolve_doc_uid(args.ref)
    if not doc_uid:
        print("Paper not found.")
        return

    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, url, published_at, collected_at FROM tech_documents WHERE doc_uid=%s",
                (doc_uid,),
            )
            meta = cur.fetchone()

            cur.execute(
                "SELECT section_index, section_title, LENGTH(section_text) FROM paper_sections WHERE doc_uid=%s ORDER BY section_index LIMIT 20",
                (doc_uid,),
            )
            sections = cur.fetchall()

            cur.execute(
                "SELECT table_index, caption, page_hint, image_path FROM paper_tables WHERE doc_uid=%s ORDER BY table_index LIMIT 20",
                (doc_uid,),
            )
            tables = cur.fetchall()

            cur.execute(
                "SELECT figure_index, caption, page_hint, image_path FROM paper_figures WHERE doc_uid=%s ORDER BY figure_index LIMIT 20",
                (doc_uid,),
            )
            figures = cur.fetchall()

            cur.execute(
                "SELECT chunk_index, LEFT(chunk_text, 220), char_len FROM tech_document_chunks WHERE doc_uid=%s ORDER BY chunk_index LIMIT 5",
                (doc_uid,),
            )
            chunks = cur.fetchall()

    print("doc_uid:", doc_uid)
    print("title:", meta[0])
    print("url:", meta[1])
    print("published_at:", meta[2])
    print("collected_at:", meta[3])
    print("\n[Sections]")
    for s in sections:
        print(f"idx={s[0]} | title={s[1]} | len={s[2]}")
    print("\n[Tables]")
    for t in tables:
        print(f"idx={t[0]} | page={t[2]} | caption={t[1]} | image={t[3]}")
    print("\n[Figures]")
    for f in figures:
        print(f"idx={f[0]} | page={f[2]} | caption={f[1]} | image={f[3]}")
    print("\n[Sample Chunks]")
    for c in chunks:
        print(f"idx={c[0]} | len={c[2]} | text={c[1]}")


if __name__ == "__main__":
    main()
