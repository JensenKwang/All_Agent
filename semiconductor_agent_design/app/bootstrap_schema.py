from app.db.neo4j_db import ensure_constraints
from app.db.qdrant import ensure_collection
from app.db.schema import ensure_postgres_schema


QDRANT_COLLECTIONS = [
    "irds_chunks",
    "jedec_chunks",
    "paper_chunks",
    "tech_blog_chunks",
    "news_chunks",
]


def main() -> None:
    ensure_postgres_schema()
    for name in QDRANT_COLLECTIONS:
        ensure_collection(name)
    ensure_constraints()
    print("[OK] Full schema bootstrap complete (Postgres + Qdrant + Neo4j)")


if __name__ == "__main__":
    main()
