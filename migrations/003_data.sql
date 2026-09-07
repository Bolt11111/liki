CREATE TABLE data_raw_payloads (
  raw_payload_id text PRIMARY KEY,
  artifact_id text NOT NULL REFERENCES artifacts,
  content_hash text NOT NULL,
  provider text NOT NULL,
  source_uri text NOT NULL,
  retrieved_at timestamptz NOT NULL,
  provider_revision_id text,
  transport_metadata jsonb NOT NULL,
  UNIQUE(artifact_id, provider, source_uri, retrieved_at)
);
CREATE TABLE dataset_manifests (
  dataset_snapshot_id text PRIMARY KEY,
  manifest_artifact_id text NOT NULL REFERENCES artifacts,
  content_hash text NOT NULL,
  quality_status text NOT NULL CHECK(quality_status IN ('pass','warn','fail','quarantined')),
  raw_payload_hashes text[] NOT NULL,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(manifest_artifact_id)
);
CREATE TABLE instrument_specifications (
  instrument_specification_id text PRIMARY KEY,
  specification_artifact_id text NOT NULL REFERENCES artifacts,
  instrument_id text NOT NULL,
  venue text NOT NULL,
  effective_from timestamptz NOT NULL,
  effective_to timestamptz,
  source_raw_payload_id text NOT NULL REFERENCES data_raw_payloads,
  historical_approximation text,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(effective_to IS NULL OR effective_to > effective_from),
  UNIQUE(specification_artifact_id)
);
CREATE TABLE instrument_lifecycle_events (
  lifecycle_event_id text PRIMARY KEY,
  lifecycle_artifact_id text NOT NULL REFERENCES artifacts,
  instrument_id text NOT NULL,
  event_kind text NOT NULL,
  effective_at timestamptz NOT NULL,
  source_raw_payload_id text NOT NULL REFERENCES data_raw_payloads,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(lifecycle_artifact_id)
);
CREATE INDEX data_raw_payload_hash ON data_raw_payloads(content_hash);
CREATE INDEX instrument_specification_as_of ON instrument_specifications(instrument_id,effective_from,effective_to);
CREATE TRIGGER data_raw_payloads_immutable BEFORE UPDATE OR DELETE ON data_raw_payloads FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER dataset_manifests_immutable BEFORE UPDATE OR DELETE ON dataset_manifests FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER instrument_specifications_immutable BEFORE UPDATE OR DELETE ON instrument_specifications FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER instrument_lifecycle_events_immutable BEFORE UPDATE OR DELETE ON instrument_lifecycle_events FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
