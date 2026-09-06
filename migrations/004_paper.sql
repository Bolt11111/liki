CREATE TABLE paper_runs (
  paper_run_id text PRIMARY KEY,
  status text NOT NULL CHECK(status IN ('RECONCILE_ONLY','ACTIVE','STOPPED','FAILED')),
  policy_version text NOT NULL,
  risk_config_artifact_id text NOT NULL REFERENCES artifacts,
  execution_config_artifact_id text NOT NULL REFERENCES artifacts,
  reporting_currency text NOT NULL,
  started_by text NOT NULL REFERENCES principals,
  reconciled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE paper_orders (
  paper_order_id text PRIMARY KEY,
  client_order_id text NOT NULL UNIQUE,
  paper_run_id text NOT NULL REFERENCES paper_runs,
  strategy_version_id text NOT NULL,
  instrument_id text NOT NULL,
  venue_id text NOT NULL,
  side text NOT NULL CHECK(side IN ('BUY','SELL')),
  order_type text NOT NULL CHECK(order_type IN ('MARKET','LIMIT')),
  time_in_force text NOT NULL CHECK(time_in_force IN ('GTC','IOC','FOK')),
  price numeric,
  quantity numeric NOT NULL CHECK(quantity > 0),
  reduce_only boolean NOT NULL DEFAULT false,
  post_only boolean NOT NULL DEFAULT false,
  information_cutoff_time timestamptz NOT NULL,
  signal_ready_time timestamptz NOT NULL,
  order_eligible_time timestamptz NOT NULL,
  decision_time timestamptz NOT NULL,
  submitted_time timestamptz,
  ack_time timestamptz,
  final_state text NOT NULL CHECK(final_state IN ('INTENT','PRETRADE_VALIDATED','SUBMITTED','ACKNOWLEDGED','UNKNOWN_RECONCILING','PARTIALLY_FILLED','AMENDED','CANCEL_PENDING','FILLED','CANCELLED','REJECTED','EXPIRED')),
  filled_quantity numeric NOT NULL DEFAULT 0 CHECK(filled_quantity >= 0 AND filled_quantity <= quantity),
  raw_venue_semantics_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  intent_json jsonb NOT NULL,
  reservation_id text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(information_cutoff_time <= signal_ready_time AND signal_ready_time <= order_eligible_time AND order_eligible_time <= decision_time),
  CHECK((order_type = 'LIMIT' AND price IS NOT NULL) OR (order_type = 'MARKET' AND price IS NULL))
);
CREATE TABLE paper_fills (
  paper_fill_id text PRIMARY KEY,
  paper_order_id text NOT NULL REFERENCES paper_orders,
  fill_sequence integer NOT NULL CHECK(fill_sequence > 0),
  fill_time timestamptz NOT NULL,
  price numeric NOT NULL CHECK(price > 0),
  quantity numeric NOT NULL CHECK(quantity > 0),
  fee_amount numeric NOT NULL,
  fee_asset text,
  liquidity_flag text CHECK(liquidity_flag IN ('MAKER','TAKER')),
  execution_model_version text NOT NULL,
  external_fill_key text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(paper_order_id, fill_sequence)
);
CREATE TABLE risk_reservations (
  reservation_id text PRIMARY KEY,
  paper_run_id text NOT NULL REFERENCES paper_runs,
  paper_order_id text UNIQUE REFERENCES paper_orders,
  pool_id text NOT NULL,
  envelope_version text NOT NULL,
  original_amount numeric NOT NULL CHECK(original_amount > 0),
  working_amount numeric NOT NULL CHECK(working_amount >= 0),
  position_amount numeric NOT NULL DEFAULT 0 CHECK(position_amount >= 0),
  state text NOT NULL CHECK(state IN ('HELD','CONVERTED','RELEASED','UNRECONCILED')),
  expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK(working_amount + position_amount = original_amount)
);
ALTER TABLE paper_orders ADD CONSTRAINT paper_orders_reservation_fk
  FOREIGN KEY(reservation_id) REFERENCES risk_reservations(reservation_id);
CREATE TABLE paper_positions (
  paper_run_id text NOT NULL REFERENCES paper_runs,
  venue_id text NOT NULL,
  instrument_id text NOT NULL,
  quantity numeric NOT NULL,
  cash_currency text NOT NULL,
  realized_pnl numeric NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(paper_run_id, venue_id, instrument_id)
);
CREATE TABLE paper_cash_ledger (
  paper_cash_entry_id text PRIMARY KEY,
  paper_run_id text NOT NULL REFERENCES paper_runs,
  paper_fill_id text NOT NULL UNIQUE REFERENCES paper_fills,
  currency text NOT NULL,
  delta numeric NOT NULL,
  balance_after numeric NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE emergency_stop_events (
  emergency_stop_id text PRIMARY KEY,
  paper_run_id text NOT NULL REFERENCES paper_runs,
  scope_type text NOT NULL CHECK(scope_type IN ('GLOBAL','VENUE','STRATEGY')),
  scope_id text,
  active boolean NOT NULL DEFAULT true,
  reason_code text NOT NULL,
  automatic boolean NOT NULL,
  actor_id text NOT NULL REFERENCES principals,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK((scope_type = 'GLOBAL' AND scope_id IS NULL) OR (scope_type <> 'GLOBAL' AND scope_id IS NOT NULL))
);
CREATE INDEX paper_orders_run_state ON paper_orders(paper_run_id, final_state);
CREATE INDEX reservations_pool_state ON risk_reservations(paper_run_id, pool_id, state);
CREATE INDEX stops_scope ON emergency_stop_events(paper_run_id, scope_type, scope_id) WHERE active;
