ALTER TABLE verifier_keys ADD COLUMN code_hash text;
UPDATE verifier_keys SET enabled=false WHERE code_hash IS NULL;
ALTER TABLE verifier_keys ADD CONSTRAINT enabled_verifier_requires_code
  CHECK(NOT enabled OR code_hash LIKE 'sha256:%');
CREATE TRIGGER verifier_identity_immutable BEFORE DELETE ON verifier_keys
  FOR EACH ROW EXECUTE FUNCTION forbid_history_mutation();
CREATE FUNCTION preserve_verifier_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF (to_jsonb(NEW)-'enabled')<>(to_jsonb(OLD)-'enabled') THEN
    RAISE EXCEPTION 'VERIFIER_IDENTITY_IMMUTABLE';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER verifier_identity_update BEFORE UPDATE ON verifier_keys
  FOR EACH ROW EXECUTE FUNCTION preserve_verifier_identity();
