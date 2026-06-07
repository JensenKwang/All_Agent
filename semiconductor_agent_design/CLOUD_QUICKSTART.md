# Cloud Quickstart (Timescale + Qdrant + Neo4j)

## 1) Fill secrets
Edit `.env`:
- `POSTGRES_DSN`
- `QDRANT_API_KEY`
- `NEO4J_PASSWORD`

## 2) Rotate keys first
If any key/password was shared in chat or docs, rotate it in vendor console and update `.env`.

## 3) Install dependencies and run scheduler
```bash
pip install -r requirements.txt
python -m app.bootstrap_schema
python -m app.jobs
```

## 4) What happens on startup
- Qdrant collections are created if missing.
- Neo4j constraints/indexes are created if missing.
- APScheduler starts jobs by cadence.

## 5) Minimum smoke checks
- Timescale: run `select now();`
- Qdrant: `get_collections()` returns list
- Neo4j: `RETURN 1 AS ok`
