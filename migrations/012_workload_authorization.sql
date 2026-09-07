CREATE FUNCTION liki_current_identity()
RETURNS TABLE(principal_id text, role text, code_fingerprint text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT p.principal_id,p.role,p.code_fingerprint
  FROM public.principals p JOIN public.service_tokens t USING(principal_id)
  WHERE t.token_hash=current_setting('liki.token_hash',true)
    AND p.enabled AND t.revoked_at IS NULL AND t.expires_at>now()
$$;

CREATE FUNCTION liki_authenticate(token_digest text)
RETURNS TABLE(principal_id text, role text, code_fingerprint text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
  PERFORM set_config('liki.token_hash',token_digest,true);
  RETURN QUERY SELECT * FROM public.liki_current_identity();
END;
$$;

CREATE FUNCTION liki_has_role(allowed_roles text[]) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT EXISTS(SELECT 1 FROM public.liki_current_identity() i WHERE i.role=ANY(allowed_roles))
$$;

CREATE FUNCTION liki_owns(principal text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT EXISTS(SELECT 1 FROM public.liki_current_identity() i WHERE i.principal_id=principal)
$$;

CREATE FUNCTION liki_can_mutate_aggregate(kind text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
  SELECT public.liki_has_role(CASE
    WHEN kind IN ('candidate','snapshot','verifier_execution') THEN ARRAY['evaluator','sealed_evaluator']
    WHEN kind='holdout_query' THEN ARRAY['sealed_evaluator']
    WHEN kind IN ('campaign','research_object','trial','memory') THEN ARRAY['research']
    WHEN kind='task' THEN ARRAY['research','scheduler']
    WHEN kind IN ('dataset_snapshot','instrument_lifecycle','instrument_specification') THEN ARRAY['data']
    WHEN kind IN ('inference_request','inference_route_circuit') THEN ARRAY['inference']
    WHEN kind IN ('paper_order','paper_run','paper_safety_latch') THEN ARRAY['paper','owner','operator']
    WHEN kind='governance_proposal' THEN ARRAY['governance','owner']
    WHEN kind IN ('model','model_validation','model_drift') THEN ARRAY['governance','evaluator']
    WHEN kind IN ('governance_change_set','governance_replay','governance_schedule','policy_version','system_evolution_trial') THEN ARRAY['governance']
    WHEN kind='incident' THEN ARRAY['governance','owner','operator','scheduler','paper']
    WHEN kind IN ('notification','outbox_delivery') THEN ARRAY['governance','owner','operator','scheduler']
    ELSE ARRAY['research'] END)
$$;

REVOKE ALL ON FUNCTION liki_current_identity(),liki_authenticate(text),liki_has_role(text[]),liki_owns(text),liki_can_mutate_aggregate(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION liki_current_identity(),liki_authenticate(text),liki_has_role(text[]),liki_owns(text),liki_can_mutate_aggregate(text) TO liki_app;

DO $$
DECLARE
  item record;
  writers text[];
BEGIN
  FOR item IN SELECT tablename FROM pg_tables WHERE schemaname='public' LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',item.tablename);
    EXECUTE format('CREATE POLICY authenticated_read ON public.%I FOR SELECT TO liki_app USING (EXISTS(SELECT 1 FROM public.liki_current_identity()))',item.tablename);
    writers := CASE
      WHEN item.tablename IN ('campaigns','tasks','task_dependencies','active_task_runs','resource_leases','allocator_decisions') THEN ARRAY['research','scheduler']
      WHEN item.tablename IN ('research_objects','lineage_edges','trial_events','memory_claims') THEN ARRAY['research']
      WHEN item.tablename='memory_contamination_edges' THEN ARRAY['research','sealed_evaluator']
      WHEN item.tablename IN ('holdout_policies','holdout_query_events') THEN ARRAY['sealed_evaluator']
      WHEN item.tablename IN ('evaluation_snapshots','gate_decisions') THEN ARRAY['evaluator','sealed_evaluator']
      WHEN item.tablename='snapshot_invalidations' THEN ARRAY['governance','evaluator','sealed_evaluator']
      WHEN item.tablename IN ('data_raw_payloads','dataset_manifests','instrument_specifications','instrument_lifecycle_events') THEN ARRAY['data']
      WHEN item.tablename IN ('inference_requests','inference_attempts','context_manifests','inference_route_circuits') THEN ARRAY['inference']
      WHEN item.tablename IN ('paper_runs','paper_orders','paper_fills','risk_reservations','paper_positions','paper_cash_ledger') THEN ARRAY['paper']
      WHEN item.tablename IN ('emergency_stop_events','paper_safety_latches') THEN ARRAY['paper','owner','operator']
      WHEN item.tablename IN ('governance_proposals','governance_reviews') THEN ARRAY['governance','owner']
      WHEN item.tablename IN ('model_inventory','model_cards','model_validations','model_drift_observations') THEN ARRAY['governance','evaluator']
      WHEN item.tablename IN ('policy_versions','governance_change_sets','governance_replays','system_evolution_trials','system_benchmark_exposures','governance_schedules') THEN ARRAY['governance']
      WHEN item.tablename IN ('incidents','incident_events') THEN ARRAY['governance','owner','operator','scheduler','paper']
      WHEN item.tablename IN ('notification_records','notification_deliveries','telegram_inbox') THEN ARRAY['governance','owner','operator','scheduler']
      ELSE ARRAY[]::text[] END;
    IF cardinality(writers)>0 THEN
      EXECUTE format('CREATE POLICY workload_insert ON public.%I FOR INSERT TO liki_app WITH CHECK (public.liki_has_role(%L::text[]))',item.tablename,writers);
      EXECUTE format('CREATE POLICY workload_update ON public.%I FOR UPDATE TO liki_app USING (public.liki_has_role(%L::text[])) WITH CHECK (public.liki_has_role(%L::text[]))',item.tablename,writers,writers);
    END IF;
  END LOOP;
END;
$$;

CREATE POLICY event_append ON event_log FOR INSERT TO liki_app
  WITH CHECK(liki_owns(principal_id) AND liki_can_mutate_aggregate(aggregate_type));
CREATE POLICY aggregate_insert ON aggregates FOR INSERT TO liki_app
  WITH CHECK(liki_can_mutate_aggregate(aggregate_type));
CREATE POLICY aggregate_update ON aggregates FOR UPDATE TO liki_app
  USING(liki_can_mutate_aggregate(aggregate_type)) WITH CHECK(liki_can_mutate_aggregate(aggregate_type));
DROP POLICY authenticated_read ON artifacts;
CREATE POLICY classified_read ON artifacts FOR SELECT TO liki_app USING
  (EXISTS(SELECT 1 FROM liki_current_identity()) AND (classification<>'SEALED' OR liki_has_role(ARRAY['sealed_evaluator'])));
CREATE POLICY artifact_append ON artifacts FOR INSERT TO liki_app WITH CHECK
  (liki_owns(producer_id) AND (classification<>'SEALED' OR liki_has_role(ARRAY['sealed_evaluator'])) AND
   (liki_has_role(ARRAY['research','evaluator','sealed_evaluator','data','paper','inference','governance']) OR
    (liki_has_role(ARRAY['owner']) AND schema_name='governance/owner-decision-attestation/v1')));
CREATE POLICY evidence_append ON evidence FOR INSERT TO liki_app WITH CHECK
  (liki_owns(admitted_by) AND liki_has_role(ARRAY['evaluator','sealed_evaluator','data']) AND
   EXISTS(SELECT 1 FROM artifacts a WHERE a.artifact_id=evidence.artifact_id));
CREATE POLICY outbox_append ON transactional_outbox FOR INSERT TO liki_app WITH CHECK
  (EXISTS(SELECT 1 FROM event_log e WHERE e.event_id=transactional_outbox.event_id AND liki_owns(e.principal_id)));
CREATE POLICY outbox_update ON transactional_outbox FOR UPDATE TO liki_app
  USING(liki_has_role(ARRAY['scheduler','governance'])) WITH CHECK(liki_has_role(ARRAY['scheduler','governance']));
CREATE POLICY safety_update_runs ON paper_runs FOR UPDATE TO liki_app
  USING(liki_has_role(ARRAY['owner','operator'])) WITH CHECK(liki_has_role(ARRAY['owner','operator']));
CREATE POLICY safety_update_orders ON paper_orders FOR UPDATE TO liki_app
  USING(liki_has_role(ARRAY['owner','operator'])) WITH CHECK(liki_has_role(ARRAY['owner','operator']));
CREATE POLICY safety_update_reservations ON risk_reservations FOR UPDATE TO liki_app
  USING(liki_has_role(ARRAY['owner','operator'])) WITH CHECK(liki_has_role(ARRAY['owner','operator']));

CREATE FUNCTION liki_bind_provenance() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
DECLARE key text; value text;
BEGIN
  IF current_user<>'liki_app' THEN RETURN NEW; END IF;
  FOREACH key IN ARRAY ARRAY['producer_id','created_by','actor_id','opened_by','started_by','principal_id'] LOOP
    value := to_jsonb(NEW)->>key;
    IF value IS NOT NULL AND NOT public.liki_owns(value) THEN
      RAISE EXCEPTION 'FORGED_PROVENANCE' USING ERRCODE='42501';
    END IF;
  END LOOP;
  RETURN NEW;
END;
$$;
DO $$
DECLARE item record;
BEGIN
  FOR item IN SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('principals','service_tokens','schema_migrations') LOOP
    EXECUTE format('CREATE TRIGGER bind_insert_provenance BEFORE INSERT ON public.%I FOR EACH ROW EXECUTE FUNCTION public.liki_bind_provenance()',item.tablename);
  END LOOP;
END;
$$;

CREATE FUNCTION liki_restrict_safety_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF current_user<>'liki_app' OR NOT public.liki_has_role(ARRAY['owner','operator']) THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='paper_orders' AND (
    (to_jsonb(NEW)-ARRAY['final_state','updated_at'])<>(to_jsonb(OLD)-ARRAY['final_state','updated_at']) OR
    to_jsonb(NEW)->>'final_state' NOT IN ('CANCELLED','CANCEL_PENDING','UNKNOWN_RECONCILING')) THEN
      RAISE EXCEPTION 'SAFETY_ACTION_MUST_REDUCE_RISK' USING ERRCODE='42501';
  ELSIF TG_TABLE_NAME='paper_runs' AND (
    (to_jsonb(NEW)-ARRAY['status','updated_at'])<>(to_jsonb(OLD)-ARRAY['status','updated_at']) OR
    to_jsonb(NEW)->>'status' NOT IN ('STOPPED','RECONCILE_ONLY')) THEN
      RAISE EXCEPTION 'SAFETY_ACTION_MUST_REDUCE_RISK' USING ERRCODE='42501';
  ELSIF TG_TABLE_NAME='risk_reservations' AND (
    (to_jsonb(NEW)-ARRAY['working_amount','released_amount','state','updated_at'])<>(to_jsonb(OLD)-ARRAY['working_amount','released_amount','state','updated_at']) OR
    (to_jsonb(NEW)->>'working_amount')::numeric>(to_jsonb(OLD)->>'working_amount')::numeric OR
    (to_jsonb(NEW)->>'released_amount')::numeric<(to_jsonb(OLD)->>'released_amount')::numeric) THEN
      RAISE EXCEPTION 'SAFETY_ACTION_MUST_REDUCE_RISK' USING ERRCODE='42501';
  ELSIF TG_TABLE_NAME='governance_proposals' AND (
    (to_jsonb(NEW)-ARRAY['owner_decision','status','updated_at'])<>(to_jsonb(OLD)-ARRAY['owner_decision','status','updated_at']) OR
    (to_jsonb(NEW)->>'status'<>to_jsonb(OLD)->>'status' AND to_jsonb(NEW)->>'status'<>'VETOED')) THEN
      RAISE EXCEPTION 'OWNER_CANNOT_PROMOTE_POLICY_DIRECTLY' USING ERRCODE='42501';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER safety_only_update BEFORE UPDATE ON paper_orders FOR EACH ROW EXECUTE FUNCTION liki_restrict_safety_mutation();
CREATE TRIGGER safety_only_update BEFORE UPDATE ON paper_runs FOR EACH ROW EXECUTE FUNCTION liki_restrict_safety_mutation();
CREATE TRIGGER safety_only_update BEFORE UPDATE ON risk_reservations FOR EACH ROW EXECUTE FUNCTION liki_restrict_safety_mutation();
CREATE TRIGGER safety_only_update BEFORE UPDATE ON governance_proposals FOR EACH ROW EXECUTE FUNCTION liki_restrict_safety_mutation();
REVOKE SELECT ON service_tokens FROM liki_app;
