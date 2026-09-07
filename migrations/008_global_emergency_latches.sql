CREATE TABLE paper_safety_latches (
  safety_latch_id text PRIMARY KEY,
  scope_type text NOT NULL CHECK(scope_type IN ('GLOBAL','VENUE')),
  scope_id text,
  active boolean NOT NULL DEFAULT true,
  reason_code text NOT NULL,
  automatic boolean NOT NULL,
  actor_id text NOT NULL REFERENCES principals,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK((scope_type = 'GLOBAL' AND scope_id IS NULL) OR (scope_type = 'VENUE' AND scope_id IS NOT NULL))
);
CREATE UNIQUE INDEX paper_safety_latches_active_scope
  ON paper_safety_latches(scope_type, COALESCE(scope_id, '')) WHERE active;
