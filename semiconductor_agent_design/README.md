# Copy `.env.example` to `.env` before running.

## 1) Bring up infra
# docker compose up -d --build

## 2) Run scheduler logs
# docker compose logs -f scheduler

## 3) Stop
# docker compose down

Services:
- Postgres/Timescale: localhost:5432
- Qdrant: localhost:6333
- Neo4j Browser: http://localhost:7474
- MinIO Console: http://localhost:9001
