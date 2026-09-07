"""Scoped, deterministic command entrypoint for persisted research gates."""

from __future__ import annotations

import argparse
import base64
import os
import stat
from pathlib import Path
from typing import Literal

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import Field, ValidationError

from liki.core import Contract, DomainError, canonical, database_config
from liki.data.models import DatasetManifest, RawPayload
from liki.data_service import DataService
from liki.evaluation import EvaluationSnapshot, Evaluator, GateInput, GateReentry
from liki.research import Research, ResearchObject, Trial
from liki.scheduler import Campaign, Scheduler
from liki.store import Credential, Store
from liki.verification import VerificationRunner


class Command(Contract):
    action: Literal["campaign", "artifact", "dataset", "register", "trial", "snapshot",
                    "verify", "decide", "reenter", "audit"]
    payload: dict


class ArtifactInput(Contract):
    content: dict
    schema_name: str = Field(min_length=1)
    classification: Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL"]
    policy_version: str = Field(min_length=1)


class RawInput(Contract):
    metadata: dict
    payload_base64: str = Field(min_length=1)


class DatasetInput(Contract):
    manifest: DatasetManifest
    raw_payloads: tuple[RawInput, ...] = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)


class VerifyInput(Contract):
    snapshot_id: str = Field(min_length=1)
    strategy_version_id: str = Field(min_length=1)
    gate_id: Literal[0, 1, 2, 3, 4, 5]
    operation_key: str = Field(min_length=1)


def execute(store: Store, credential: Credential, command: Command,
            runner: VerificationRunner | None = None) -> dict:
    body = command.payload
    match command.action:
        case "campaign":
            return {"campaign_id": Scheduler(store).campaign(credential, Campaign.model_validate(body))}
        case "artifact":
            artifact_request = ArtifactInput.model_validate(body)
            with store.transaction(credential) as (conn, actor):
                aid = store.put_artifact(conn, actor, **artifact_request.model_dump())
                row = store.artifact(conn, actor, aid)
                return {"artifact_id": aid, "content_hash": row["content_hash"]}
        case "dataset":
            dataset_request = DatasetInput.model_validate(body)
            payloads = tuple(RawPayload.model_validate({
                **raw.metadata, "payload_bytes": base64.b64decode(raw.payload_base64, validate=True)
            }) for raw in dataset_request.raw_payloads)
            return {"artifact_id": DataService(store).persist_dataset(credential, dataset_request.manifest,
                payloads, operation_key=dataset_request.operation_key, task_id=dataset_request.task_id,
                policy_version=dataset_request.policy_version)}
        case "register":
            return {"object_id": Research(store).register(credential, ResearchObject.model_validate(body))}
        case "trial":
            return {"trial_event_id": Research(store).trial(credential, Trial.model_validate(body))}
        case "snapshot":
            return {"snapshot_id": Evaluator(store).snapshot(credential, EvaluationSnapshot.model_validate(body))}
        case "verify":
            verify_request = VerifyInput.model_validate(body)
            if runner is None:
                raise DomainError("VERIFIER_NOT_CONFIGURED")
            return {"evidence_id": runner.execute(credential, **verify_request.model_dump())}
        case "decide":
            return Evaluator(store).gate(credential, GateInput.model_validate(body))
        case "reenter":
            return Evaluator(store).reenter(credential, GateReentry.model_validate(body))
        case "audit":
            if body:
                raise DomainError("INVALID_AUDIT_REQUEST")
            with store.transaction(credential) as (conn, actor):
                actor.require("read")
                return store.audit(conn)


def read_secret(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise DomainError("SECRET_FILE_PERMISSIONS_UNSAFE")
        value = stream.read(8193)
    if not value or len(value) > 8192:
        raise DomainError("SECRET_FILE_INVALID")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--verifier-key-id")
    parser.add_argument("--verifier-key-file", type=Path)
    args = parser.parse_args(argv)
    try:
        credential = Credential(read_secret(args.credential_file).decode().strip())
        if args.request_file.stat().st_size > 10 * 1024 * 1024:
            raise DomainError("REQUEST_TOO_LARGE")
        command = Command.model_validate_json(args.request_file.read_bytes())
        store = Store(database_config()["app_dsn"])
        runner = None
        if command.action == "verify":
            if not args.verifier_key_id or not args.verifier_key_file:
                raise DomainError("VERIFIER_NOT_CONFIGURED")
            key = Ed25519PrivateKey.from_private_bytes(read_secret(args.verifier_key_file))
            runner = VerificationRunner(store, args.verifier_key_id, key)
        result = execute(store, credential, command, runner)
    except DomainError as error:
        result = {"error": error.code}
    except ValidationError as error:
        result = {"error": "INVALID_REQUEST", "fields": [
            {"location": list(item["loc"]), "type": item["type"]} for item in error.errors()
        ]}
    except psycopg.Error:
        result = {"error": "DATABASE_UNAVAILABLE"}
    except (ValueError, OSError):
        result = {"error": "INVALID_RUNTIME_INPUT"}
    print(canonical(result))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
