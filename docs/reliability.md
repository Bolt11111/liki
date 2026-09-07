# Backup, restore, and recovery evidence

`liki.backup.backup_database` creates an encrypted PostgreSQL custom archive and a manifest. The archive and its manifest are published crash-consistently and durably: the encrypted archive is fsynced, then linked into place without overwriting an existing file; only after that is the fsynced manifest published. A crash can leave an unpaired archive, which restore refuses rather than treating as a valid backup; it can never publish a manifest that points at an unpublished archive.

The versioned manifest binds SHA-256 values for ciphertext and plaintext, exact public-table totals, ordered migration hashes, and a verified immutable event-chain/projection checkpoint. Its keyed MAC prevents an archive owner from silently editing recovery metadata. Backups use one exported repeatable-read PostgreSQL snapshot for both the checkpoint and `pg_dump`, so the manifest describes the archive's logical database state rather than a later moving database state.

## Safe restore drill

Provision a dedicated **empty** drill database outside the production storage failure domain. It must not contain public objects or non-system schemas. Set its DSN only in the process environment; the drill command does not accept a DSN argument, avoiding credential exposure in shell history.

```bash
export LIKI_RESTORE_TARGET_DSN='postgresql://…/liki_restore_drill'
uv run python scripts/restore_drill.py --source /secure/backups/liki.dump --key-file /secure/keys/liki-backup.key
```

The drill performs the empty-target check before decrypting, runs `pg_restore` in one transaction, then verifies every public-table total, migration hash, immutable event hash chain, and aggregate projection against the manifest. It reports monotonic restore duration. The target stays populated after a successful drill for inspection; provisioning systems may remove only a database they created and identified exactly for that drill.

## RPO and RTO semantics

`recovery_report` records the fingerprint of `fsync`, `full_page_writes`, `synchronous_commit`, `wal_level`, and `archive_mode`. With durable local commit settings it reports `process_crash_rpo: DURABLE_COMMIT`, meaning an application-success acknowledgement survived an ordinary process/host-service crash while durable storage remains healthy. Otherwise it reports `NOT_MET`.

`storage_disaster_rpo` is always `NOT_MEASURED` until a deployed cross-failure-domain replication and restore/failover drill measures it. A local backup or a successful restore drill does not prove zero data loss after storage, host, or zone loss. Backup metadata derives `process_crash_rpo` from the database settings seen at the snapshot and never upgrades that value based on the existence of an archive. Similarly, a database restore duration is not a measurement of the five-minute control-plane or thirty-minute full-service RTO; those remain `NOT_MEASURED` until an end-to-end deployment drill records them.

Schedule backup creation and this restore command through the deployment scheduler, retain archives and keys in separate access-controlled failure domains, and retain the resulting report as recovery evidence. PostgreSQL WAL/PITR and off-host replication are deployment services, not capabilities that this local archive alone can claim to provide.
