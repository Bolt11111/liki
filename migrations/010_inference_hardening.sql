-- Equivalent controlled contexts can be attached to different semantic requests.
ALTER TABLE context_manifests DROP CONSTRAINT IF EXISTS context_manifests_manifest_hash_key;
