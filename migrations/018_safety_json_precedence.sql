CREATE OR REPLACE FUNCTION liki_restrict_safety_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public AS $$
BEGIN
  IF current_user<>'liki_app' OR NOT public.liki_has_role(ARRAY['owner','operator']) THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='paper_orders' AND (
    (to_jsonb(NEW)-ARRAY['final_state','raw_venue_semantics_json','updated_at'])<>(to_jsonb(OLD)-ARRAY['final_state','raw_venue_semantics_json','updated_at']) OR
    ((to_jsonb(NEW)->'raw_venue_semantics_json')-ARRAY['safety_latch_id','cancel_reason'])<>((to_jsonb(OLD)->'raw_venue_semantics_json')-ARRAY['safety_latch_id','cancel_reason']) OR
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
