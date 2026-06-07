# DB Schema Draft for Semiconductor Expert Agent

## 1) Recommended DB by Domain
- Domain 1 (정형 시계열/공시/가격/거시): PostgreSQL + TimescaleDB
- Domain 2/3/4/5 (문서 RAG): Qdrant (vector + metadata filter)
- Causal/ontology/provenance graph: Neo4j
- Raw archive (PDF/XML/HTML): S3-compatible object storage

---

## 2) PostgreSQL (Timescale) - Core Tables

```sql
CREATE TABLE companies (
  company_code TEXT PRIMARY KEY,
  company_name TEXT NOT NULL,
  market TEXT,
  country TEXT DEFAULT 'KR'
);

CREATE TABLE metric_observations (
  id BIGSERIAL PRIMARY KEY,
  company_code TEXT REFERENCES companies(company_code),
  domain TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  metric_value DOUBLE PRECISION NOT NULL,
  unit TEXT,
  is_proxy BOOLEAN DEFAULT FALSE,
  proxy_for TEXT,
  observed_at TIMESTAMPTZ NOT NULL,
  published_at TIMESTAMPTZ NOT NULL,
  valid_from TIMESTAMPTZ NOT NULL,
  valid_to TIMESTAMPTZ,
  source_tier SMALLINT NOT NULL CHECK (source_tier BETWEEN 1 AND 4),
  confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  prov_entity TEXT NOT NULL,
  prov_activity TEXT,
  prov_agent TEXT,
  source_url TEXT,
  extra JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX idx_metric_obs_company_time ON metric_observations(company_code, observed_at DESC);
CREATE INDEX idx_metric_obs_metric_time ON metric_observations(metric_name, observed_at DESC);
CREATE INDEX idx_metric_obs_domain ON metric_observations(domain);
CREATE INDEX idx_metric_obs_jsonb ON metric_observations USING GIN(extra);

CREATE TABLE disclosures (
  id BIGSERIAL PRIMARY KEY,
  company_code TEXT REFERENCES companies(company_code),
  rcept_no TEXT UNIQUE,
  report_type TEXT,
  title TEXT,
  published_at TIMESTAMPTZ NOT NULL,
  raw_object_path TEXT,
  extracted JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE price_daily (
  company_code TEXT REFERENCES companies(company_code),
  trade_date DATE NOT NULL,
  open NUMERIC(18,4),
  high NUMERIC(18,4),
  low NUMERIC(18,4),
  close NUMERIC(18,4),
  volume BIGINT,
  PRIMARY KEY (company_code, trade_date)
);

CREATE TABLE feature_store (
  id BIGSERIAL PRIMARY KEY,
  company_code TEXT REFERENCES companies(company_code),
  horizon TEXT NOT NULL,
  feature_name TEXT NOT NULL,
  feature_value DOUBLE PRECISION NOT NULL,
  as_of TIMESTAMPTZ NOT NULL,
  published_cutoff TIMESTAMPTZ NOT NULL,
  confidence DOUBLE PRECISION CHECK (confidence >= 0 AND confidence <= 1),
  provenance_refs TEXT[] DEFAULT '{}'
);

CREATE INDEX idx_feature_store_key ON feature_store(company_code, horizon, as_of DESC);
```

Timescale hypertable recommendation:
- `metric_observations(observed_at)`
- `price_daily(trade_date)`

---

## 3) Qdrant - Collections and Payload

Collection plan:
- `irds_chunks`
- `jedec_chunks`
- `paper_chunks`
- `tech_blog_chunks`
- `news_chunks`

Common payload schema:
```json
{
  "doc_id": "uuid",
  "chunk_id": "uuid#03",
  "domain": "domain4_papers",
  "source": "arxiv",
  "source_tier": 2,
  "company_mentions": ["000660", "005930"],
  "tech_tags": ["HBM", "TSV", "yield"],
  "published_at": "2026-04-01T00:00:00Z",
  "language": "en",
  "confidence": 0.78,
  "prov_entity": "arxiv:2501.12345",
  "url": "https://arxiv.org/abs/2501.12345"
}
```

Recommended vector setup:
- dense vector: `text-embedding-3-large` (or org standard)
- optional sparse vector: BM25/SPLADE hybrid
- metadata filters must support: `domain`, `source_tier`, `company_mentions`, `published_at`

---

## 4) Neo4j - Ontology / Causal Graph

Node labels:
- `Company`, `BusinessUnit`, `ProcessNode`, `Product`, `TechEvent`, `Metric`, `Document`

Edge types:
- `(:TechEvent)-[:AFFECTS]->(:Metric)`
- `(:Metric)-[:IMPACTS]->(:Company)`
- `(:Document)-[:EVIDENCE_FOR]->(:TechEvent)`
- `(:Company)-[:OPERATES]->(:BusinessUnit)`
- `(:Product)-[:BUILT_ON]->(:ProcessNode)`

Cypher draft:
```cypher
CREATE CONSTRAINT company_code IF NOT EXISTS
FOR (c:Company) REQUIRE c.company_code IS UNIQUE;

CREATE INDEX tech_event_time IF NOT EXISTS
FOR (e:TechEvent) ON (e.published_at);

CREATE INDEX metric_name IF NOT EXISTS
FOR (m:Metric) ON (m.name);
```

Example causal path query:
```cypher
MATCH p = (d:Document)-[:EVIDENCE_FOR]->(e:TechEvent)-[:AFFECTS]->(m:Metric)-[:IMPACTS]->(c:Company {company_code:'000660'})
WHERE e.published_at >= datetime('2025-01-01T00:00:00Z')
RETURN p
ORDER BY e.published_at DESC
LIMIT 20;
```

---

## 5) Why this stack fits your use case
- Postgres/Timescale: 워크포워드 백테스트와 피처 생성에 강함
- Qdrant: RAG에서 메타필터 + 최신성 제어 + 소스 신뢰도 필터가 쉬움
- Neo4j: "기술 이벤트 -> 제조 KPI -> 재무 -> 주가" 인과 경로 설명 가능

## 6) Minimal deployment order (MVP -> Production)
1. Postgres + Qdrant 먼저 구축
2. 수집 파이프라인 연결 후 RAG 응답 검증
3. Neo4j를 인과설명/감사 레이어로 추가
4. 마지막으로 재학습/가중치 조정 자동화
