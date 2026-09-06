CREATE TABLE notification_records (
  notification_id text PRIMARY KEY,
  deduplication_key text NOT NULL UNIQUE,
  content_hash text NOT NULL,
  urgency text NOT NULL CHECK(urgency IN ('CRITICAL','HIGH','NORMAL','DIGEST')),
  classification text NOT NULL CHECK(classification IN ('PUBLIC','INTERNAL')),
  recipient_ref text NOT NULL,
  title text NOT NULL,
  message text NOT NULL,
  required_action text,
  deadline_at timestamptz,
  object_id text,
  event_id text NOT NULL REFERENCES event_log,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE notification_deliveries (
  notification_id text PRIMARY KEY REFERENCES notification_records,
  outbox_id text NOT NULL UNIQUE REFERENCES transactional_outbox,
  provider_message_id text NOT NULL,
  delivered_at timestamptz NOT NULL,
  event_id text NOT NULL REFERENCES event_log
);
CREATE TABLE telegram_inbox (
  update_id bigint PRIMARY KEY,
  request_hash text NOT NULL,
  principal_id text NOT NULL REFERENCES principals,
  command text NOT NULL,
  notification_id text NOT NULL REFERENCES notification_records,
  received_at timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER notification_immutable BEFORE UPDATE OR DELETE ON notification_records
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER delivery_immutable BEFORE UPDATE OR DELETE ON notification_deliveries
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE TRIGGER inbox_immutable BEFORE UPDATE OR DELETE ON telegram_inbox
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
