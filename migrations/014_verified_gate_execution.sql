CREATE TABLE verifier_keys (
  verifier_key_id text PRIMARY KEY,
  principal_id text NOT NULL REFERENCES principals,
  verifier_version text NOT NULL,
  public_key bytea NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE verifier_executions (
  verifier_execution_id text PRIMARY KEY,
  verifier_key_id text NOT NULL REFERENCES verifier_keys,
  snapshot_id text NOT NULL REFERENCES evaluation_snapshots,
  strategy_version_id text NOT NULL REFERENCES research_objects,
  gate_id integer NOT NULL CHECK(gate_id BETWEEN 0 AND 13),
  input_hash text NOT NULL,
  report_artifact_id text NOT NULL UNIQUE REFERENCES artifacts,
  report_hash text NOT NULL,
  manifest jsonb NOT NULL,
  signature bytea NOT NULL,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE verifier_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE verifier_executions ENABLE ROW LEVEL SECURITY;
CREATE POLICY verifier_key_read ON verifier_keys FOR SELECT TO liki_app
  USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY verifier_execution_read ON verifier_executions FOR SELECT TO liki_app
  USING(EXISTS(SELECT 1 FROM liki_current_identity()));
CREATE POLICY verifier_execution_insert ON verifier_executions FOR INSERT TO liki_app WITH CHECK
  (EXISTS(SELECT 1 FROM verifier_keys k WHERE k.verifier_key_id=verifier_executions.verifier_key_id
          AND k.enabled AND liki_owns(k.principal_id)) AND liki_has_role(ARRAY['evaluator','sealed_evaluator']));
CREATE TRIGGER verification_immutable BEFORE UPDATE OR DELETE ON verifier_executions
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
