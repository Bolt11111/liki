CREATE TABLE inference_requests (
  inference_request_id text PRIMARY KEY,
  semantic_task_id text NOT NULL,
  parent_run_id text,
  task_class text NOT NULL,
  criticality text NOT NULL CHECK (criticality IN ('low','normal','high','critical')),
  request_json jsonb NOT NULL,
  request_hash text NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  context_manifest_hash text NOT NULL,
  status text NOT NULL CHECK (status IN ('ADMITTED','ATTEMPTING','SEMANTIC_ACCEPTED','DECISION_USEFUL','HIBERNATED')),
  max_call_cost_usd numeric,
  max_total_attempt_cost_usd numeric,
  reserved_cost_usd numeric NOT NULL DEFAULT 0 CHECK (reserved_cost_usd >= 0),
  accrued_cost_usd numeric NOT NULL DEFAULT 0 CHECK (accrued_cost_usd >= 0),
  completed_attempt_id text,
  final_artifact_id text REFERENCES artifacts,
  failure_reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CHECK (max_call_cost_usd IS NULL OR max_call_cost_usd >= 0),
  CHECK (max_total_attempt_cost_usd IS NULL OR max_total_attempt_cost_usd >= 0)
);

CREATE TABLE context_manifests (
  context_manifest_id text PRIMARY KEY,
  inference_request_id text NOT NULL UNIQUE REFERENCES inference_requests,
  compiler_version text NOT NULL,
  retrieval_version text NOT NULL,
  required_evidence_classes text[] NOT NULL,
  candidate_evidence_ids text[] NOT NULL,
  included_evidence_ids text[] NOT NULL,
  tool_addressable_evidence_ids text[] NOT NULL,
  excluded_evidence_json jsonb NOT NULL,
  summary_artifact_ids text[] NOT NULL,
  truncation_json jsonb NOT NULL,
  egress_decision_json jsonb NOT NULL,
  completeness_status text NOT NULL CHECK (completeness_status IN ('COMPLETE_FOR_CONTRACT','INCOMPLETE_BLOCKING','INCOMPLETE_DECLARED_NONCRITICAL')),
  manifest_hash text NOT NULL UNIQUE,
  manifest_json jsonb NOT NULL,
  manifest_artifact_id text NOT NULL REFERENCES artifacts,
  created_at timestamptz NOT NULL
);

CREATE TABLE inference_attempts (
  inference_attempt_id text PRIMARY KEY,
  inference_request_id text NOT NULL REFERENCES inference_requests,
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  provider_route_id text NOT NULL,
  provider_request_id text,
  model_family text NOT NULL,
  model_version text,
  provider_reported_model text,
  reasoning_effort text NOT NULL,
  prompt_manifest_hash text NOT NULL,
  lease_fence bigint NOT NULL CHECK (lease_fence > 0),
  lease_until timestamptz NOT NULL,
  status text NOT NULL,
  http_status integer,
  error_class text,
  input_tokens bigint,
  output_tokens bigint,
  billed_tokens bigint,
  token_count_method text NOT NULL,
  pricing_plan_id text,
  fixed_call_cost_usd numeric,
  token_cost_usd numeric,
  total_cost_usd numeric NOT NULL DEFAULT 0 CHECK (total_cost_usd >= 0),
  provider_reported_cost_usd numeric,
  latency_ms integer,
  output_artifact_id text REFERENCES artifacts,
  response_hash text,
  attempt_json jsonb NOT NULL,
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  UNIQUE(inference_request_id, attempt_no),
  UNIQUE(inference_request_id, lease_fence),
  CHECK (provider_reported_cost_usd IS NULL OR provider_reported_cost_usd >= 0)
);

ALTER TABLE inference_requests
  ADD CONSTRAINT inference_requests_completed_attempt_fk
  FOREIGN KEY (completed_attempt_id) REFERENCES inference_attempts DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE inference_route_circuits (
  provider_route_id text PRIMARY KEY,
  consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  is_open boolean NOT NULL DEFAULT false,
  aggregate_version bigint NOT NULL DEFAULT 0 CHECK (aggregate_version >= 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX inference_attempts_request ON inference_attempts(inference_request_id, attempt_no);
CREATE INDEX inference_attempts_live_lease ON inference_attempts(inference_request_id, lease_until)
  WHERE status='CREATED';
CREATE INDEX inference_requests_hibernated ON inference_requests(status) WHERE status='HIBERNATED';

CREATE TRIGGER context_manifests_immutable BEFORE UPDATE OR DELETE ON context_manifests
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
