CREATE TABLE governance_lifecycle_outcomes (
  lifecycle_event_id text NOT NULL REFERENCES event_log,
  proposal_id text NOT NULL REFERENCES governance_proposals,
  lifecycle_snapshot_hash text NOT NULL,
  phase text NOT NULL CHECK(phase IN ('replay','tests','shadow','canary')),
  check_id text NOT NULL,
  check_kind text NOT NULL,
  result text NOT NULL CHECK(result IN ('PASS','FAIL')),
  result_artifact_id text NOT NULL REFERENCES artifacts,
  executed_at timestamptz NOT NULL,
  recorded_by text NOT NULL REFERENCES principals,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(lifecycle_event_id,phase,check_id)
);
CREATE INDEX governance_lifecycle_outcomes_proposal ON governance_lifecycle_outcomes(proposal_id,executed_at);
CREATE TRIGGER governance_lifecycle_outcomes_immutable BEFORE UPDATE OR DELETE ON governance_lifecycle_outcomes
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();

ALTER TABLE governance_lifecycle_outcomes ENABLE ROW LEVEL SECURITY;
CREATE FUNCTION liki_authenticated_workload() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT EXISTS(
    SELECT 1
    FROM public.principals p JOIN public.service_tokens t USING(principal_id)
    WHERE t.token_hash=current_setting('liki.token_hash',true)
      AND p.enabled AND t.revoked_at IS NULL AND t.expires_at>now()
  )
$$;
CREATE FUNCTION liki_governance_lifecycle_writer() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT EXISTS(
    SELECT 1
    FROM public.principals p JOIN public.service_tokens t USING(principal_id)
    WHERE t.token_hash=current_setting('liki.token_hash',true)
      AND p.enabled AND p.role='governance' AND t.revoked_at IS NULL AND t.expires_at>now()
  )
$$;
REVOKE ALL ON FUNCTION liki_authenticated_workload() FROM PUBLIC;
REVOKE ALL ON FUNCTION liki_governance_lifecycle_writer() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION liki_authenticated_workload(),liki_governance_lifecycle_writer() TO liki_app;
CREATE POLICY governance_lifecycle_outcomes_read ON governance_lifecycle_outcomes FOR SELECT TO liki_app
  USING(liki_authenticated_workload());
CREATE POLICY governance_lifecycle_outcomes_insert ON governance_lifecycle_outcomes FOR INSERT TO liki_app
  WITH CHECK(liki_governance_lifecycle_writer());
