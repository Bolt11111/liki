CREATE TABLE policy_versions (
  policy_id text NOT NULL,
  policy_version text NOT NULL,
  content_hash text NOT NULL,
  status text NOT NULL CHECK(status IN ('DRAFT','EFFECTIVE','RETIRED','ROLLED_BACK')),
  policy_artifact_id text NOT NULL REFERENCES artifacts,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now(),
  effective_at timestamptz,
  retired_at timestamptz,
  governance_proposal_id text,
  safe_bounds_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  rollback_to_version text,
  PRIMARY KEY(policy_id,policy_version),
  UNIQUE(policy_id,content_hash)
);
CREATE UNIQUE INDEX one_effective_policy_scope ON policy_versions(policy_id) WHERE status='EFFECTIVE';

CREATE TABLE governance_proposals (
  proposal_id text PRIMARY KEY,
  proposal_version integer NOT NULL CHECK(proposal_version>0),
  authored_by text NOT NULL REFERENCES principals,
  package jsonb NOT NULL,
  classification jsonb,
  lifecycle jsonb NOT NULL DEFAULT '{}'::jsonb,
  synthesis jsonb,
  owner_delivery jsonb,
  owner_decision jsonb,
  status text NOT NULL,
  approval_snapshot_hash text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(proposal_id,proposal_version)
);
CREATE TABLE governance_reviews (
  council_review_id text PRIMARY KEY,
  proposal_id text NOT NULL REFERENCES governance_proposals,
  review jsonb NOT NULL,
  evidence_manifest_artifact_id text NOT NULL REFERENCES artifacts,
  created_at timestamptz NOT NULL,
  UNIQUE(proposal_id,council_review_id)
);
CREATE INDEX governance_reviews_proposal ON governance_reviews(proposal_id,created_at);

CREATE TABLE governance_change_sets (
  change_set_id text PRIMARY KEY,
  change_set jsonb NOT NULL,
  created_by text NOT NULL REFERENCES principals,
  state_version bigint NOT NULL CHECK(state_version>0),
  created_at timestamptz NOT NULL,
  revalidated_at timestamptz,
  promoted_at timestamptz
);
CREATE TABLE governance_replays (
  replay_id text PRIMARY KEY,
  proposal_id text REFERENCES governance_proposals,
  input_artifact_id text NOT NULL REFERENCES artifacts,
  result_artifact_id text NOT NULL REFERENCES artifacts,
  input_hash text NOT NULL,
  result jsonb NOT NULL,
  produced_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE system_evolution_trials (
  trial_id text PRIMARY KEY,
  trial jsonb NOT NULL,
  produced_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE system_benchmark_exposures (
  trial_id text NOT NULL REFERENCES system_evolution_trials,
  benchmark_id text NOT NULL,
  evidence_artifact_id text NOT NULL REFERENCES artifacts,
  purpose text NOT NULL,
  consumed_at timestamptz NOT NULL,
  PRIMARY KEY(trial_id,benchmark_id,evidence_artifact_id)
);

CREATE TABLE model_inventory (
  model_id text PRIMARY KEY,
  version text NOT NULL,
  status text NOT NULL CHECK(status IN ('DEVELOPMENT','SHADOW','APPROVED','WATCH','SUSPENDED','RETIRED')),
  materiality text NOT NULL CHECK(materiality IN ('CRITICAL','MATERIAL','SUPPORTING')),
  record jsonb NOT NULL,
  record_artifact_id text NOT NULL REFERENCES artifacts,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  validation_due_at timestamptz,
  retired_at timestamptz,
  replacement_model_id text REFERENCES model_inventory,
  UNIQUE(model_id,version)
);
CREATE TABLE model_cards (
  model_id text NOT NULL REFERENCES model_inventory,
  card_artifact_id text NOT NULL REFERENCES artifacts,
  card jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(model_id,card_artifact_id)
);
CREATE TABLE model_validations (
  validation_id text PRIMARY KEY,
  model_id text NOT NULL REFERENCES model_inventory,
  validation jsonb NOT NULL,
  validation_artifact_id text NOT NULL REFERENCES artifacts,
  validator_principal text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL
);
CREATE TABLE model_drift_observations (
  observation_id text PRIMARY KEY,
  model_id text NOT NULL REFERENCES model_inventory,
  observation jsonb NOT NULL,
  measurement_artifact_id text NOT NULL REFERENCES artifacts,
  observed_at timestamptz NOT NULL
);

CREATE TABLE incidents (
  incident_id text PRIMARY KEY,
  incident jsonb NOT NULL,
  severity text NOT NULL CHECK(severity IN ('SEV0','SEV1','SEV2','SEV3')),
  status text NOT NULL CHECK(status IN ('OPEN','CONTAINED','RECONCILING','RESOLVED','CLOSED')),
  state_version bigint NOT NULL CHECK(state_version>0),
  opened_by text NOT NULL REFERENCES principals,
  opened_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE incident_events (
  incident_event_id text PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents,
  event_id text NOT NULL REFERENCES event_log,
  transition jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(incident_id,event_id)
);

CREATE TABLE governance_schedules (
  schedule_id text PRIMARY KEY,
  cadence text NOT NULL CHECK(cadence IN ('MONTHLY','EMERGENCY')),
  next_due_at timestamptz NOT NULL,
  last_run_at timestamptz,
  state_version bigint NOT NULL CHECK(state_version>0),
  status text NOT NULL CHECK(status IN ('SCHEDULED','DUE','COMPLETED','PAUSED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER policy_versions_immutable BEFORE DELETE ON policy_versions FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER governance_reviews_immutable BEFORE UPDATE OR DELETE ON governance_reviews FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER governance_replays_immutable BEFORE UPDATE OR DELETE ON governance_replays FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER system_trials_immutable BEFORE UPDATE OR DELETE ON system_evolution_trials FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER model_validations_immutable BEFORE UPDATE OR DELETE ON model_validations FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER model_drift_immutable BEFORE UPDATE OR DELETE ON model_drift_observations FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER incident_events_immutable BEFORE UPDATE OR DELETE ON incident_events FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
