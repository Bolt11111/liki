CREATE TABLE model_evidence_links (
  evidence_link_id text PRIMARY KEY,
  model_id text NOT NULL REFERENCES model_inventory,
  artifact_id text NOT NULL REFERENCES artifacts,
  evidence_role text NOT NULL CHECK(evidence_role IN ('DEVELOPMENT','VALIDATION','MONITORING','DEVELOPMENT_USED')),
  prior_evidence_role text CHECK(prior_evidence_role IN ('VALIDATION')),
  linked_by text NOT NULL REFERENCES principals,
  linked_at timestamptz NOT NULL,
  UNIQUE(model_id,artifact_id,evidence_role)
);
CREATE TABLE model_effective_challenges (
  challenge_id text PRIMARY KEY,
  model_id text NOT NULL REFERENCES model_inventory,
  validation_id text NOT NULL REFERENCES model_validations,
  challenger_model_id text REFERENCES model_inventory,
  challenge_artifact_id text NOT NULL REFERENCES artifacts,
  validator_principal text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL,
  UNIQUE(model_id,validation_id)
);
CREATE TABLE model_use_exceptions (
  exception_id text PRIMARY KEY,
  model_id text NOT NULL REFERENCES model_inventory,
  limitation text NOT NULL,
  reason text NOT NULL,
  compensating_control text NOT NULL,
  expires_at timestamptz NOT NULL,
  approved_by text NOT NULL REFERENCES principals,
  approval_artifact_id text NOT NULL REFERENCES artifacts,
  created_at timestamptz NOT NULL,
  revoked_at timestamptz,
  CHECK(expires_at > created_at)
);
CREATE TABLE model_retirements (
  model_id text PRIMARY KEY REFERENCES model_inventory,
  retirement_artifact_id text NOT NULL REFERENCES artifacts,
  retired_by text NOT NULL REFERENCES principals,
  replacement_model_id text REFERENCES model_inventory,
  retired_at timestamptz NOT NULL
);

CREATE TABLE incident_evidence_snapshots (
  incident_id text NOT NULL REFERENCES incidents,
  artifact_id text NOT NULL REFERENCES artifacts,
  captured_by text NOT NULL REFERENCES principals,
  captured_at timestamptz NOT NULL,
  PRIMARY KEY(incident_id,artifact_id)
);
CREATE TABLE incident_corrective_actions (
  corrective_action_id text PRIMARY KEY,
  incident_id text NOT NULL REFERENCES incidents,
  action_description text NOT NULL,
  completion_artifact_id text NOT NULL REFERENCES artifacts,
  regression_artifact_ids text[] NOT NULL CHECK(cardinality(regression_artifact_ids)>0),
  verified_by text NOT NULL REFERENCES principals,
  verified_at timestamptz NOT NULL
);
CREATE TABLE incident_cause_links (
  incident_id text NOT NULL REFERENCES incidents,
  related_incident_id text NOT NULL REFERENCES incidents,
  relationship_artifact_id text NOT NULL REFERENCES artifacts,
  linked_by text NOT NULL REFERENCES principals,
  linked_at timestamptz NOT NULL,
  PRIMARY KEY(incident_id,related_incident_id),
  CHECK(incident_id <> related_incident_id)
);
CREATE TABLE incident_promotion_freezes (
  incident_id text PRIMARY KEY REFERENCES incidents,
  reason text NOT NULL,
  frozen_by text NOT NULL REFERENCES principals,
  frozen_at timestamptz NOT NULL,
  lifted_at timestamptz,
  lift_artifact_id text REFERENCES artifacts
);

CREATE TABLE reliability_sli_definitions (
  sli_id text PRIMARY KEY,
  service_scope text NOT NULL CHECK(service_scope IN
    ('CONTROL_PLANE','SCHEDULER_PROGRESS','INFERENCE_ROUTE','EVALUATOR_BACKTEST','MARKET_DATA_FRESHNESS','PAPER_RECONCILIATION','EVIDENCE_DURABILITY')),
  target_basis_points integer NOT NULL CHECK(target_basis_points BETWEEN 0 AND 10000),
  window_seconds integer NOT NULL CHECK(window_seconds BETWEEN 60 AND 31536000),
  breach_threshold integer NOT NULL CHECK(breach_threshold > 0),
  policy_version text NOT NULL,
  definition_artifact_id text NOT NULL REFERENCES artifacts,
  created_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL,
  UNIQUE(service_scope,policy_version)
);
CREATE TABLE reliability_sli_samples (
  sample_id text PRIMARY KEY,
  sli_id text NOT NULL REFERENCES reliability_sli_definitions,
  observed_at timestamptz NOT NULL,
  is_good boolean NOT NULL,
  measurement_artifact_id text NOT NULL REFERENCES artifacts,
  recorded_by text NOT NULL REFERENCES principals,
  UNIQUE(sli_id,observed_at,measurement_artifact_id)
);
CREATE INDEX reliability_samples_window ON reliability_sli_samples(sli_id,observed_at);
CREATE TABLE reliability_slo_windows (
  window_id text PRIMARY KEY,
  sli_id text NOT NULL REFERENCES reliability_sli_definitions,
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  total_samples integer NOT NULL CHECK(total_samples > 0),
  good_samples integer NOT NULL CHECK(good_samples BETWEEN 0 AND total_samples),
  compliance_basis_points integer NOT NULL CHECK(compliance_basis_points BETWEEN 0 AND 10000),
  target_basis_points integer NOT NULL CHECK(target_basis_points BETWEEN 0 AND 10000),
  error_budget_consumed_basis_points integer NOT NULL CHECK(error_budget_consumed_basis_points BETWEEN 0 AND 10000),
  status text NOT NULL CHECK(status IN ('COMPLIANT','BREACHED')),
  evaluated_by text NOT NULL REFERENCES principals,
  evaluated_at timestamptz NOT NULL,
  UNIQUE(sli_id,window_start,window_end)
);
CREATE TABLE reliability_promotion_freezes (
  freeze_id text PRIMARY KEY,
  sli_id text NOT NULL REFERENCES reliability_sli_definitions,
  triggering_window_id text NOT NULL REFERENCES reliability_slo_windows,
  frozen_by text NOT NULL REFERENCES principals,
  frozen_at timestamptz NOT NULL,
  lifted_at timestamptz,
  lift_artifact_id text REFERENCES artifacts
);
CREATE UNIQUE INDEX one_active_reliability_promotion_freeze ON reliability_promotion_freezes(sli_id) WHERE lifted_at IS NULL;

ALTER TABLE model_evidence_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_effective_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_use_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_retirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident_evidence_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident_corrective_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident_cause_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE incident_promotion_freezes ENABLE ROW LEVEL SECURITY;
ALTER TABLE reliability_sli_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE reliability_sli_samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE reliability_slo_windows ENABLE ROW LEVEL SECURITY;
ALTER TABLE reliability_promotion_freezes ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE item text;
BEGIN
  FOREACH item IN ARRAY ARRAY['model_evidence_links','model_effective_challenges','model_use_exceptions','model_retirements','incident_evidence_snapshots','incident_corrective_actions','incident_cause_links','incident_promotion_freezes','reliability_sli_definitions','reliability_sli_samples','reliability_slo_windows','reliability_promotion_freezes'] LOOP
    EXECUTE format('CREATE POLICY authenticated_read ON public.%I FOR SELECT TO liki_app USING (EXISTS(SELECT 1 FROM public.liki_current_identity()))', item);
  END LOOP;
END;
$$;
CREATE POLICY model_risk_write ON model_evidence_links FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance'])) WITH CHECK (liki_has_role(ARRAY['governance']));
CREATE POLICY model_challenge_write ON model_effective_challenges FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance'])) WITH CHECK (liki_has_role(ARRAY['governance']));
CREATE POLICY model_exception_write ON model_use_exceptions FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance'])) WITH CHECK (liki_has_role(ARRAY['governance']));
CREATE POLICY model_retirement_write ON model_retirements FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance'])) WITH CHECK (liki_has_role(ARRAY['governance']));
CREATE POLICY incident_evidence_write ON incident_evidence_snapshots FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance','owner','operator','scheduler','paper'])) WITH CHECK (liki_has_role(ARRAY['governance','owner','operator','scheduler','paper']));
CREATE POLICY incident_corrective_write ON incident_corrective_actions FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance'])) WITH CHECK (liki_has_role(ARRAY['governance']));
CREATE POLICY incident_cause_write ON incident_cause_links FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance','owner','operator','scheduler','paper'])) WITH CHECK (liki_has_role(ARRAY['governance','owner','operator','scheduler','paper']));
CREATE POLICY incident_freeze_write ON incident_promotion_freezes FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance','owner','operator','scheduler','paper'])) WITH CHECK (liki_has_role(ARRAY['governance','owner','operator','scheduler','paper']));
CREATE POLICY reliability_definition_write ON reliability_sli_definitions FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance'])) WITH CHECK (liki_has_role(ARRAY['governance']));
CREATE POLICY reliability_sample_write ON reliability_sli_samples FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance','scheduler','operator'])) WITH CHECK (liki_has_role(ARRAY['governance','scheduler','operator']));
CREATE POLICY reliability_window_write ON reliability_slo_windows FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance','scheduler','operator'])) WITH CHECK (liki_has_role(ARRAY['governance','scheduler','operator']));
CREATE POLICY reliability_freeze_write ON reliability_promotion_freezes FOR ALL TO liki_app USING (liki_has_role(ARRAY['governance','operator'])) WITH CHECK (liki_has_role(ARRAY['governance','operator']));

CREATE TRIGGER model_evidence_immutable BEFORE UPDATE OR DELETE ON model_evidence_links FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER model_challenge_immutable BEFORE UPDATE OR DELETE ON model_effective_challenges FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER incident_snapshot_immutable BEFORE UPDATE OR DELETE ON incident_evidence_snapshots FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER incident_action_immutable BEFORE UPDATE OR DELETE ON incident_corrective_actions FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER incident_cause_immutable BEFORE UPDATE OR DELETE ON incident_cause_links FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER slo_definition_immutable BEFORE UPDATE OR DELETE ON reliability_sli_definitions FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER slo_sample_immutable BEFORE UPDATE OR DELETE ON reliability_sli_samples FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER slo_window_immutable BEFORE UPDATE OR DELETE ON reliability_slo_windows FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
