CREATE TABLE portfolio_models (
  portfolio_model_id text PRIMARY KEY,
  version text NOT NULL,
  model_kind text NOT NULL CHECK(model_kind IN ('allocation','risk','sizing','scenario')),
  record_artifact_id text NOT NULL REFERENCES artifacts,
  created_by text NOT NULL REFERENCES principals,
  event_id text NOT NULL UNIQUE REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(portfolio_model_id,version)
);
CREATE TABLE portfolio_evaluations (
  portfolio_evaluation_id text PRIMARY KEY,
  portfolio_candidate_id text NOT NULL REFERENCES research_objects,
  campaign_id text NOT NULL REFERENCES campaigns,
  trial_family_id text NOT NULL,
  allocator_model_id text NOT NULL REFERENCES portfolio_models,
  dataset_artifact_ids text[] NOT NULL,
  strategy_version_ids text[] NOT NULL,
  execution_mode text NOT NULL CHECK(execution_mode='RESEARCH_ONLY'),
  result_artifact_id text NOT NULL REFERENCES artifacts,
  challenger_artifact_id text NOT NULL REFERENCES artifacts,
  event_id text NOT NULL UNIQUE REFERENCES event_log,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE portfolio_trials (
  portfolio_trial_id text PRIMARY KEY,
  portfolio_evaluation_id text NOT NULL REFERENCES portfolio_evaluations,
  trial_family_id text NOT NULL,
  trial_kind text NOT NULL CHECK(trial_kind IN ('universe','allocation','sizing','rebalance','objective','constraint','validation','forward_feedback')),
  semantic_hash text NOT NULL,
  configuration_artifact_id text NOT NULL REFERENCES artifacts,
  event_id text NOT NULL UNIQUE REFERENCES event_log,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(trial_family_id,semantic_hash)
);
CREATE TABLE portfolio_strategy_status_events (
  portfolio_strategy_status_event_id text PRIMARY KEY,
  portfolio_evaluation_id text NOT NULL REFERENCES portfolio_evaluations,
  strategy_version_id text NOT NULL REFERENCES research_objects,
  state text NOT NULL CHECK(state IN ('HEALTHY','WATCH','DEGRADED','SUSPENDED','DORMANT','RETIRED')),
  reason text NOT NULL,
  regime_rule_artifact_id text REFERENCES artifacts,
  refreshed_evidence_ids text[] NOT NULL,
  event_id text NOT NULL UNIQUE REFERENCES event_log,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE portfolio_readiness_packets (
  portfolio_readiness_packet_id text PRIMARY KEY,
  portfolio_evaluation_id text NOT NULL REFERENCES portfolio_evaluations,
  packet_artifact_id text NOT NULL UNIQUE REFERENCES artifacts,
  execution_mode text NOT NULL CHECK(execution_mode='RESEARCH_ONLY'),
  event_id text NOT NULL UNIQUE REFERENCES event_log,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX portfolio_evaluation_candidate ON portfolio_evaluations(portfolio_candidate_id,created_at);
CREATE INDEX portfolio_trials_family ON portfolio_trials(trial_family_id,created_at);
CREATE INDEX portfolio_status_strategy ON portfolio_strategy_status_events(strategy_version_id,created_at DESC);

ALTER TABLE portfolio_models ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_trials ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_strategy_status_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_readiness_packets ENABLE ROW LEVEL SECURITY;

CREATE POLICY portfolio_models_read ON portfolio_models FOR SELECT TO liki_app USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY portfolio_evaluations_read ON portfolio_evaluations FOR SELECT TO liki_app USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY portfolio_trials_read ON portfolio_trials FOR SELECT TO liki_app USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY portfolio_status_read ON portfolio_strategy_status_events FOR SELECT TO liki_app USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY portfolio_packets_read ON portfolio_readiness_packets FOR SELECT TO liki_app USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY portfolio_models_insert ON portfolio_models FOR INSERT TO liki_app WITH CHECK(liki_has_role(ARRAY['research']));
CREATE POLICY portfolio_evaluations_insert ON portfolio_evaluations FOR INSERT TO liki_app WITH CHECK(liki_has_role(ARRAY['research']));
CREATE POLICY portfolio_trials_insert ON portfolio_trials FOR INSERT TO liki_app WITH CHECK(liki_has_role(ARRAY['research']));
CREATE POLICY portfolio_status_insert ON portfolio_strategy_status_events FOR INSERT TO liki_app WITH CHECK(liki_has_role(ARRAY['research']));
CREATE POLICY portfolio_packets_insert ON portfolio_readiness_packets FOR INSERT TO liki_app WITH CHECK(liki_has_role(ARRAY['research']));

CREATE TRIGGER portfolio_models_provenance BEFORE INSERT ON portfolio_models FOR EACH ROW EXECUTE FUNCTION liki_bind_provenance();
CREATE TRIGGER portfolio_evaluations_provenance BEFORE INSERT ON portfolio_evaluations FOR EACH ROW EXECUTE FUNCTION liki_bind_provenance();
CREATE TRIGGER portfolio_trials_provenance BEFORE INSERT ON portfolio_trials FOR EACH ROW EXECUTE FUNCTION liki_bind_provenance();
CREATE TRIGGER portfolio_status_provenance BEFORE INSERT ON portfolio_strategy_status_events FOR EACH ROW EXECUTE FUNCTION liki_bind_provenance();
CREATE TRIGGER portfolio_packets_provenance BEFORE INSERT ON portfolio_readiness_packets FOR EACH ROW EXECUTE FUNCTION liki_bind_provenance();
CREATE TRIGGER portfolio_models_immutable BEFORE UPDATE OR DELETE ON portfolio_models FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER portfolio_evaluations_immutable BEFORE UPDATE OR DELETE ON portfolio_evaluations FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER portfolio_trials_immutable BEFORE UPDATE OR DELETE ON portfolio_trials FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER portfolio_status_immutable BEFORE UPDATE OR DELETE ON portfolio_strategy_status_events FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER portfolio_packets_immutable BEFORE UPDATE OR DELETE ON portfolio_readiness_packets FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
