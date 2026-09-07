CREATE TABLE campaigns (
  campaign_id text PRIMARY KEY, purpose text NOT NULL, start_rule text NOT NULL,
  stopping_rule text NOT NULL, horizon_at timestamptz NOT NULL,
  usd_budget numeric NOT NULL CHECK(usd_budget >= 0), allocated_usd numeric NOT NULL DEFAULT 0,
  token_budget bigint NOT NULL CHECK(token_budget >= 0), compute_seconds_budget numeric NOT NULL,
  statistical_budget integer NOT NULL CHECK(statistical_budget>=0),
  created_by text NOT NULL REFERENCES principals, created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(allocated_usd>=0 AND allocated_usd<=usd_budget)
);
CREATE TABLE tasks (
  task_id text PRIMARY KEY, campaign_id text NOT NULL REFERENCES campaigns,
  parent_task_id text REFERENCES tasks, semantic_hash text NOT NULL,
  purpose text NOT NULL, expected_artifact_schema text NOT NULL,
  task_class text NOT NULL, lane_class text NOT NULL, handler text NOT NULL, inputs jsonb NOT NULL,
  budget_usd numeric NOT NULL CHECK(budget_usd>=0), child_allocated_usd numeric NOT NULL DEFAULT 0,
  voi_lower_bound numeric NOT NULL, novelty numeric NOT NULL, information_value numeric NOT NULL,
  max_retries integer NOT NULL CHECK(max_retries>=0), timeout_sec integer NOT NULL CHECK(timeout_sec>0),
  status text NOT NULL CHECK(status IN ('queued','running','hibernating','completed','failed','killed','expired','QUARANTINED','blocked_by_budget','blocked_by_cooldown')),
  independent_if_parent_fails boolean NOT NULL, available_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(), state_version bigint NOT NULL,
  UNIQUE(campaign_id,semantic_hash), CHECK(child_allocated_usd>=0 AND child_allocated_usd<=budget_usd)
);
CREATE TABLE task_dependencies (
  task_id text NOT NULL REFERENCES tasks, depends_on text NOT NULL REFERENCES tasks,
  PRIMARY KEY(task_id,depends_on), CHECK(task_id<>depends_on)
);
CREATE TABLE active_task_runs (
  run_id text PRIMARY KEY, task_id text NOT NULL REFERENCES tasks,
  parent_task_id text REFERENCES tasks, branch_id text, idea_id text,
  agent_role_id text NOT NULL, lane_id text, worker_id text NOT NULL REFERENCES principals,
  task_class text NOT NULL, status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), queued_at timestamptz, started_at timestamptz,
  heartbeat_at timestamptz, completed_at timestamptz, killed_at timestamptz, kill_reason text,
  current_gate_id text, current_action text NOT NULL, expected_artifact_schema text NOT NULL,
  expected_artifact_id text REFERENCES artifacts, active_lease_id text,
  priority numeric NOT NULL, retry_count integer NOT NULL, max_retries integer NOT NULL,
  timeout_sec integer NOT NULL, hibernation_until timestamptz, why_running text NOT NULL,
  state_version bigint NOT NULL, metadata_json jsonb NOT NULL
);
CREATE TABLE resource_leases (
  lease_id text PRIMARY KEY, run_id text NOT NULL REFERENCES active_task_runs,
  worker_id text NOT NULL REFERENCES principals, fencing_token text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL, heartbeat_at timestamptz NOT NULL,
  released_at timestamptz, resource_class text NOT NULL
);
CREATE TABLE allocator_decisions (
  allocation_id text PRIMARY KEY, candidate_task_ids text[] NOT NULL, chosen_task_ids text[] NOT NULL,
  excluded_json jsonb NOT NULL, features_json jsonb NOT NULL, displaced_task_ids text[] NOT NULL,
  propensity_json jsonb NOT NULL, policy_version text NOT NULL,
  exploration_reason text NOT NULL, event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE research_objects (
  object_id text PRIMARY KEY, object_type text NOT NULL CHECK(object_type IN
    ('hypothesis','mechanism','strategy','strategy_version','branch','experiment','portfolio_candidate')),
  campaign_id text NOT NULL REFERENCES campaigns, artifact_id text NOT NULL REFERENCES artifacts,
  created_by text NOT NULL REFERENCES principals, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE lineage_edges (
  parent_id text NOT NULL REFERENCES research_objects, child_id text NOT NULL REFERENCES research_objects,
  edge_type text NOT NULL CHECK(edge_type IN ('derived_from','parameter_variant_of','mechanism_variant_of',
    'data_variant_of','execution_variant_of','portfolio_variant_of','independent_reimplementation_of',
    'ablation_of','combination_of','reproduction_of')),
  PRIMARY KEY(parent_id,child_id,edge_type), CHECK(parent_id<>child_id)
);
CREATE TABLE trial_events (
  trial_event_id text PRIMARY KEY, campaign_id text NOT NULL REFERENCES campaigns,
  trial_family_id text NOT NULL, strategy_version_id text NOT NULL REFERENCES research_objects,
  parent_trial_event_id text REFERENCES trial_events, trial_type text NOT NULL, selection_reason text NOT NULL,
  mechanism_id text, parameter_space_hash text, dataset_snapshot_ids text[] NOT NULL,
  metric_ids text[] NOT NULL, started_at timestamptz NOT NULL, completed_at timestamptz,
  scientific_retry_of text REFERENCES trial_events, infrastructure_retry boolean NOT NULL,
  contamination_tags text[] NOT NULL, metadata_json jsonb NOT NULL, operation_key text NOT NULL UNIQUE,
  semantic_hash text NOT NULL, event_id text NOT NULL REFERENCES event_log
);
CREATE TABLE holdout_policies (
  holdout_id text PRIMARY KEY, dataset_artifact_id text NOT NULL REFERENCES artifacts,
  dataset_role text NOT NULL CHECK(dataset_role IN ('GUARD','SEALED','FORWARD')),
  allowed_family_ids text[] NOT NULL, query_budget integer NOT NULL CHECK(query_budget>=0),
  queries integer NOT NULL DEFAULT 0 CHECK(queries>=0), retired boolean NOT NULL DEFAULT false,
  policy_version text NOT NULL, output_granularity text NOT NULL CHECK(output_granularity IN ('category','boolean'))
);
CREATE TABLE holdout_query_events (
  holdout_query_id text PRIMARY KEY, holdout_id text NOT NULL REFERENCES holdout_policies,
  campaign_id text NOT NULL REFERENCES campaigns, strategy_version_id text NOT NULL REFERENCES research_objects,
  trial_family_id text NOT NULL, request_hash text NOT NULL, response_category text NOT NULL,
  query_policy_version text NOT NULL, response_granularity text NOT NULL,
  budget_before integer NOT NULL, budget_after integer NOT NULL,
  researcher_exposure boolean NOT NULL, event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(holdout_id,strategy_version_id),
  CHECK(budget_after=budget_before-1 AND budget_after>=0)
);
CREATE TABLE memory_claims (
  memory_id text PRIMARY KEY, claim text NOT NULL, claim_type text NOT NULL,
  source_evidence_ids text[] NOT NULL, confidence_state text NOT NULL CHECK(confidence_state IN ('unverified','candidate','replicated','invalidated')),
  market_scope text[] NOT NULL, mechanism_scope text[] NOT NULL, regime_scope text[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), last_revalidated_at timestamptz NOT NULL,
  policy_version text NOT NULL, contamination_tags text[] NOT NULL,
  known_counterevidence_ids text[] NOT NULL, supersedes text[] NOT NULL, created_by text NOT NULL REFERENCES principals
);
CREATE TABLE memory_contamination_edges (
  source_id text NOT NULL, descendant_id text NOT NULL REFERENCES research_objects,
  tag text NOT NULL, event_id text NOT NULL REFERENCES event_log, PRIMARY KEY(source_id,descendant_id,tag)
);
CREATE TABLE gate_decisions (
  gate_decision_id text PRIMARY KEY, strategy_version_id text NOT NULL REFERENCES research_objects,
  gate_id integer NOT NULL CHECK(gate_id BETWEEN 0 AND 13), snapshot_id text NOT NULL REFERENCES evaluation_snapshots,
  gate_version text NOT NULL, gate_state_version_before bigint NOT NULL, gate_state_version_after bigint NOT NULL,
  state_before text NOT NULL, state_after text NOT NULL,
  decision text NOT NULL CHECK(decision IN ('PASS','BORDERLINE','FAIL','BLOCKED','NOT_APPLICABLE','NEEDS_MORE_INFORMATION')),
  reason_code text NOT NULL, decision_reason text NOT NULL, actor_id text NOT NULL REFERENCES principals,
  policy_version text NOT NULL, evidence_ids text[] NOT NULL, artifact_ids text[] NOT NULL,
  metrics_json jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  event_id text NOT NULL REFERENCES event_log, UNIQUE(strategy_version_id,gate_state_version_before),
  CHECK(gate_state_version_after=gate_state_version_before+1)
);
CREATE INDEX tasks_ready ON tasks(status,available_at,task_class);
CREATE INDEX runs_task ON active_task_runs(task_id,created_at);
CREATE INDEX lease_expiry ON resource_leases(expires_at) WHERE released_at IS NULL;
CREATE INDEX trial_family ON trial_events(trial_family_id,campaign_id);
CREATE TRIGGER trials_immutable BEFORE UPDATE OR DELETE ON trial_events FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER queries_immutable BEFORE UPDATE OR DELETE ON holdout_query_events FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER gates_immutable BEFORE UPDATE OR DELETE ON gate_decisions FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
