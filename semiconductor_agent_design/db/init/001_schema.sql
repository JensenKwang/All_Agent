CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS companies (
  company_code TEXT PRIMARY KEY,
  company_name TEXT NOT NULL,
  market TEXT,
  country TEXT DEFAULT 'KR'
);

CREATE TABLE IF NOT EXISTS metric_observations (
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

CREATE INDEX IF NOT EXISTS idx_metric_obs_company_time ON metric_observations(company_code, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_metric_obs_metric_time ON metric_observations(metric_name, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_metric_obs_domain ON metric_observations(domain);
CREATE INDEX IF NOT EXISTS idx_metric_obs_jsonb ON metric_observations USING GIN(extra);

SELECT create_hypertable('metric_observations', by_range('observed_at'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS disclosures (
  id BIGSERIAL PRIMARY KEY,
  company_code TEXT REFERENCES companies(company_code),
  rcept_no TEXT UNIQUE,
  report_type TEXT,
  title TEXT,
  published_at TIMESTAMPTZ NOT NULL,
  raw_object_path TEXT,
  extracted JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS price_daily (
  company_code TEXT REFERENCES companies(company_code),
  trade_date DATE NOT NULL,
  open NUMERIC(18,4),
  high NUMERIC(18,4),
  low NUMERIC(18,4),
  close NUMERIC(18,4),
  volume BIGINT,
  PRIMARY KEY (company_code, trade_date)
);

CREATE TABLE IF NOT EXISTS feature_store (
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

CREATE INDEX IF NOT EXISTS idx_feature_store_key ON feature_store(company_code, horizon, as_of DESC);
