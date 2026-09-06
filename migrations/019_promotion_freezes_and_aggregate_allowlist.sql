CREATE OR REPLACE FUNCTION liki_can_mutate_aggregate(kind text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT public.liki_has_role(CASE
    WHEN kind IN ('candidate','snapshot','verifier_execution') THEN ARRAY['evaluator','sealed_evaluator']
    WHEN kind='holdout_query' THEN ARRAY['sealed_evaluator']
    WHEN kind IN ('campaign','research_object','trial','memory','portfolio_model','portfolio_evaluation',
      'portfolio_trial','portfolio_strategy_monitor','portfolio_readiness_packet') THEN ARRAY['research']
    WHEN kind='task' THEN ARRAY['research','scheduler']
    WHEN kind IN ('dataset_snapshot','instrument_lifecycle','instrument_specification') THEN ARRAY['data']
    WHEN kind IN ('inference_request','inference_route_circuit') THEN ARRAY['inference']
    WHEN kind IN ('paper_order','paper_run','paper_safety_latch') THEN ARRAY['paper','owner','operator']
    WHEN kind='governance_proposal' THEN ARRAY['governance','owner']
    WHEN kind IN ('model','model_validation','model_drift') THEN ARRAY['governance','evaluator']
    WHEN kind IN ('governance_change_set','governance_replay','governance_schedule','policy_version',
      'system_evolution_trial') THEN ARRAY['governance']
    WHEN kind IN ('incident','reliability_sli') THEN ARRAY['governance','owner','operator','scheduler','paper']
    WHEN kind IN ('notification','outbox_delivery') THEN ARRAY['governance','owner','operator','scheduler']
    ELSE ARRAY[]::text[] END)
$$;

CREATE FUNCTION liki_guard_promotion_freeze() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE promoting boolean;
BEGIN
  IF TG_TABLE_NAME='gate_decisions' THEN
    promoting := to_jsonb(NEW)->>'decision'='PASS';
  ELSE
    promoting := to_jsonb(NEW)->>'status' IN ('PROMOTED','APPROVED','EFFECTIVE');
  END IF;
  IF promoting AND (EXISTS(SELECT 1 FROM incident_promotion_freezes WHERE lifted_at IS NULL)
      OR EXISTS(SELECT 1 FROM reliability_promotion_freezes WHERE lifted_at IS NULL)) THEN
    RAISE EXCEPTION 'PROMOTION_FROZEN' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER freeze_gate_promotion BEFORE INSERT ON gate_decisions
  FOR EACH ROW EXECUTE FUNCTION liki_guard_promotion_freeze();
CREATE TRIGGER freeze_governance_promotion BEFORE INSERT OR UPDATE ON governance_proposals
  FOR EACH ROW EXECUTE FUNCTION liki_guard_promotion_freeze();
CREATE TRIGGER freeze_model_approval BEFORE INSERT OR UPDATE ON model_inventory
  FOR EACH ROW EXECUTE FUNCTION liki_guard_promotion_freeze();
CREATE TRIGGER freeze_policy_activation BEFORE INSERT OR UPDATE ON policy_versions
  FOR EACH ROW EXECUTE FUNCTION liki_guard_promotion_freeze();
