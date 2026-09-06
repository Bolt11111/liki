CREATE TABLE schema_migrations (
  version text PRIMARY KEY, content_hash text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE principals (
  principal_id text PRIMARY KEY, role text NOT NULL CHECK (role IN
    ('owner','operator','research','evaluator','sealed_evaluator','inference','scheduler','governance','paper','data','auditor')),
  enabled boolean NOT NULL DEFAULT true, code_fingerprint text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE service_tokens (
  token_hash text PRIMARY KEY, principal_id text NOT NULL REFERENCES principals,
  expires_at timestamptz NOT NULL, revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE aggregates (
  aggregate_type text NOT NULL, aggregate_id text NOT NULL,
  version bigint NOT NULL CHECK (version > 0), state jsonb NOT NULL,
  PRIMARY KEY (aggregate_type,aggregate_id)
);
CREATE TABLE event_log (
  sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  event_id text PRIMARY KEY, event_type text NOT NULL, occurred_at_utc timestamptz NOT NULL,
  ingested_at_utc timestamptz NOT NULL DEFAULT now(),
  aggregate_type text NOT NULL, aggregate_id text NOT NULL, aggregate_version bigint NOT NULL,
  principal_id text NOT NULL REFERENCES principals, actor_type text NOT NULL,
  task_id text NOT NULL, branch_id text, strategy_version_id text,
  artifact_ids text[] NOT NULL, evidence_ids text[] NOT NULL, gate_id text,
  policy_version text NOT NULL, code_commit text NOT NULL, environment_fingerprint text NOT NULL,
  metadata jsonb NOT NULL, previous_hash text NOT NULL, event_hash text NOT NULL UNIQUE,
  operation_key text NOT NULL UNIQUE, operation_hash text NOT NULL,
  UNIQUE(aggregate_type,aggregate_id,aggregate_version)
);
CREATE TABLE transactional_outbox (
  outbox_id text PRIMARY KEY, event_id text NOT NULL REFERENCES event_log,
  topic text NOT NULL, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'PENDING'
    CHECK(status IN ('PENDING','LEASED','DELIVERED','QUARANTINED')),
  attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
  lease_token text, lease_expires_at timestamptz, delivered_at timestamptz,
  UNIQUE(event_id,topic)
);
CREATE TABLE artifacts (
  artifact_id text PRIMARY KEY, content_hash text NOT NULL, schema_name text NOT NULL,
  classification text NOT NULL CHECK(classification IN ('PUBLIC','INTERNAL','CONFIDENTIAL','SEALED')),
  producer_id text NOT NULL REFERENCES principals, environment_fingerprint text NOT NULL,
  policy_version text NOT NULL, content jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(producer_id,content_hash,schema_name)
);
CREATE TABLE evidence (
  evidence_id text PRIMARY KEY, artifact_id text NOT NULL REFERENCES artifacts,
  evidence_class text NOT NULL, epistemic_label text NOT NULL CHECK(epistemic_label IN
    ('OBSERVED_FACT','DERIVED_VALUE','MODEL_ESTIMATE','LLM_INFERENCE','HYPOTHESIS','ASSUMPTION','RECOMMENDATION','UNKNOWN')),
  role text NOT NULL CHECK(role IN ('DEVELOPMENT','GUARD','SEALED','FORWARD','SYNTHETIC','VALIDATION','DEVELOPMENT_USED')),
  available_at timestamptz NOT NULL, contamination_tags text[] NOT NULL,
  admitted_by text NOT NULL REFERENCES principals, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE evaluation_snapshots (
  snapshot_id text PRIMARY KEY, content_hash text NOT NULL UNIQUE, manifest jsonb NOT NULL,
  producer_id text NOT NULL REFERENCES principals, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE snapshot_invalidations (
  invalidation_id text PRIMARY KEY, snapshot_id text NOT NULL REFERENCES evaluation_snapshots,
  reason text NOT NULL, policy_version text NOT NULL, event_id text NOT NULL REFERENCES event_log
);
CREATE INDEX event_aggregate ON event_log(aggregate_type,aggregate_id,aggregate_version);
CREATE INDEX outbox_ready ON transactional_outbox(status,available_at);
CREATE INDEX evidence_artifact ON evidence(artifact_id);
CREATE FUNCTION forbid_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'IMMUTABLE_HISTORY'; END;
$$;
CREATE TRIGGER event_immutable BEFORE UPDATE OR DELETE ON event_log FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER artifact_immutable BEFORE UPDATE OR DELETE ON artifacts FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER evidence_immutable BEFORE UPDATE OR DELETE ON evidence FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER snapshot_immutable BEFORE UPDATE OR DELETE ON evaluation_snapshots FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
