import os
from dotenv import load_dotenv

try:
    from psycopg import connect as pg_connect  # psycopg3
except Exception:  # pragma: no cover
    import psycopg2

    def pg_connect(dsn: str):
        return psycopg2.connect(dsn)

from qdrant_client import QdrantClient
from neo4j import GraphDatabase


def mask(value: str, keep: int = 6) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep:
        return "*" * len(value)
    return value[:keep] + "*" * (len(value) - keep)


def test_timescale(dsn: str) -> None:
    with pg_connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT now(), current_database(), current_user;")
            row = cur.fetchone()
    print(f"[OK] Timescale connected | now={row[0]} db={row[1]} user={row[2]}")


def test_qdrant(url: str, api_key: str) -> None:
    client = QdrantClient(url=url, api_key=api_key)
    cols = client.get_collections().collections
    names = [c.name for c in cols]
    print(f"[OK] Qdrant connected | collections={len(names)} {names}")


def test_neo4j(uri: str, user: str, password: str, database: str) -> None:
    tried = []
    candidates = [uri]
    if uri.startswith("neo4j+s://"):
        candidates.append(uri.replace("neo4j+s://", "bolt+s://", 1))
        candidates.append(uri.replace("neo4j+s://", "bolt+ssc://", 1))
    elif uri.startswith("bolt+s://"):
        candidates.append(uri.replace("bolt+s://", "bolt+ssc://", 1))

    last_err = None
    for candidate in candidates:
        try:
            driver = GraphDatabase.driver(candidate, auth=(user, password))
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                result = session.run("RETURN 1 AS ok, datetime() AS ts")
                rec = result.single()
            driver.close()
            print(f"[OK] Neo4j connected | uri={candidate} ok={rec['ok']} ts={rec['ts']}")
            return
        except Exception as e:
            last_err = e
            tried.append(candidate)
    raise RuntimeError(f"tried={tried} error={last_err}")


def main() -> None:
    load_dotenv()

    dsn = os.getenv("POSTGRES_DSN", "")
    qdrant_url = os.getenv("QDRANT_URL", "")
    qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
    neo4j_uri = os.getenv("NEO4J_URI", "")
    neo4j_user = os.getenv("NEO4J_USER", os.getenv("NEO4J_USERNAME", "neo4j"))
    neo4j_password = os.getenv("NEO4J_PASSWORD", "")
    neo4j_database = os.getenv("NEO4J_DATABASE", "neo4j")

    print("[INFO] Starting cloud connectivity test")
    print(f"[INFO] POSTGRES_DSN set: {bool(dsn)}")
    print(f"[INFO] QDRANT_URL: {qdrant_url}")
    print(f"[INFO] QDRANT_API_KEY: {mask(qdrant_api_key)}")
    print(f"[INFO] NEO4J_URI: {neo4j_uri}")
    print(f"[INFO] NEO4J_USER: {neo4j_user}")

    try:
        test_timescale(dsn)
    except Exception as e:
        print(f"[FAIL] Timescale: {e}")

    try:
        test_qdrant(qdrant_url, qdrant_api_key)
    except Exception as e:
        print(f"[FAIL] Qdrant: {e}")

    try:
        test_neo4j(neo4j_uri, neo4j_user, neo4j_password, neo4j_database)
    except Exception as e:
        print(f"[FAIL] Neo4j: {e}")


if __name__ == "__main__":
    main()
