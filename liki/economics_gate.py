"""Signed, source-bound G6 evidence; G5 artifacts are never rewritten."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from decimal import Context, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from liki.backtest_gate import QuoteReplayData
from liki.core import DomainError, canonical, content_hash
from liki.data.models import DatasetManifest, QualityStatus
from liki.finance.contracts import UnknownContractError
from liki.finance.economics import evaluate_economics
from liki.finance.economics_contracts import EconomicsPlan, EconomicsPolicy, ExecutionTape, ImpactMeasurement, ImpactSampleSet
from liki.store import Identity, Store


def _raw(store, conn, actor, digest, artifacts, cutoff, allowed=None):
    rows = conn.execute("SELECT DISTINCT artifact_id FROM data_raw_payloads WHERE content_hash=%s ORDER BY artifact_id", (digest,)).fetchall()
    for row in rows:
        if allowed is not None and row["artifact_id"] not in allowed:
            continue
        artifact = store.artifact(conn, actor, row["artifact_id"])
        metadata = artifact["content"]["raw_payload"]
        if (artifact["created_at"] >= cutoff or metadata.get("provider_revision_id")
                or datetime.fromisoformat(metadata["retrieved_at"]) > cutoff):
            continue
        payload = base64.b64decode(artifact["content"]["payload_base64"], validate=True)
        if "sha256:" + sha256(payload).hexdigest() != digest:
            raise UnknownContractError("G6_RAW_HASH_MISMATCH")
        artifacts[artifact["artifact_id"]] = artifact
        return payload, metadata
    raise UnknownContractError("G6_PERSISTED_RAW_SOURCE_MISSING")


def _g5(store, conn, actor, obj, artifacts):
    from liki.verification import verify_execution

    decision = conn.execute("SELECT * FROM gate_decisions WHERE strategy_version_id=%s AND gate_id=5 "
        "AND decision='PASS' ORDER BY gate_state_version_after DESC LIMIT 1", (obj["object_id"],)).fetchone()
    if not decision:
        raise UnknownContractError("G6_APPLIED_G5_PASS_MISSING")
    snapshot = conn.execute("SELECT * FROM evaluation_snapshots WHERE snapshot_id=%s", (decision["snapshot_id"],)).fetchone()
    packages = []
    for eid in decision["evidence_ids"]:
        row = conn.execute("SELECT artifact_id FROM evidence WHERE evidence_id=%s", (eid,)).fetchone()
        report = store.artifact(conn, actor, row["artifact_id"])
        verify_execution(store, conn, actor, report, SimpleNamespace(snapshot_id=decision["snapshot_id"],
            strategy_version_id=obj["object_id"], gate_id=5, expected_version=decision["gate_state_version_before"]), snapshot)
        artifacts[report["artifact_id"]] = report
        package = store.artifact(conn, actor, report["content"]["package_artifact_id"])
        if package["content_hash"] != report["content"]["package_hash"] or package["schema_name"] != "backtest/protocol-report-v1":
            raise UnknownContractError("G6_G5_PACKAGE_MISMATCH")
        artifacts[package["artifact_id"]] = package
        for aid, digest in package["content"]["input_artifacts"].items():
            source = store.artifact(conn, actor, aid)
            if source["content_hash"] != digest:
                raise UnknownContractError("G6_G5_INPUT_BINDING_MISMATCH")
            artifacts[aid] = source
        packages.append(package)
    if len(packages) != 1:
        raise UnknownContractError("G6_G5_REPORT_AMBIGUOUS")
    return packages[0], decision


def _calibration(store, conn, actor, policy, tape, snapshot, artifacts) -> dict:
    groups = []
    for digests in (policy.impact.calibration_raw_hashes, policy.impact.validation_raw_hashes):
        records: list[ImpactMeasurement] = []
        for digest in digests:
            payload, _ = _raw(store, conn, actor, digest, artifacts, snapshot["created_at"])
            samples = ImpactSampleSet.model_validate_json(payload)
            if (samples.venue, samples.instrument_id) != (tape.venue, tape.instrument_id):
                raise UnknownContractError("G6_IMPACT_CALIBRATION_MARKET_MISMATCH")
            records.extend(samples.observations)
        groups.append(records)
    training, validation = groups
    if (len({x.episode_id for x in training + validation}) != len(training + validation)
            or max(x.timestamp for x in training) >= min(x.timestamp for x in validation)
            or max(x.available_at for x in training + validation) >= tape.books[0].event_time):
        raise UnknownContractError("G6_IMPACT_CALIBRATION_LEAKAGE")
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        coefficients = sorted(row.residual_impact_bps / row.participation.sqrt() for row in training)
        middle = len(coefficients) // 2
        median = coefficients[middle] if len(coefficients) % 2 else (coefficients[middle - 1] + coefficients[middle]) / 2
        bounds = (coefficients[0], median, coefficients[-1])
        if bounds != (policy.impact.lower_bps, policy.impact.central_bps, policy.impact.upper_bps):
            raise UnknownContractError("G6_IMPACT_BOUNDS_NOT_CALIBRATED")
        validation_coefficients = [row.residual_impact_bps / row.participation.sqrt() for row in validation]
        if any(not bounds[0] <= value <= bounds[2] for value in validation_coefficients):
            raise UnknownContractError("G6_IMPACT_HOLDOUT_VALIDATION_FAILED")
    return {"method": "nonnegative-square-root-participation; empirical min/median/max coefficient",
        "training_episodes": [x.episode_id for x in training], "validation_episodes": [x.episode_id for x in validation],
        "bounds": bounds, "validation_coefficients": validation_coefficients,
        "limitation": "Empirical scenario bounds, not a statistical confidence interval or live-scale validation"}


def check_economics(store: Store, conn: Any, actor: Identity, snapshot: dict, obj: dict) -> dict:
    manifest = snapshot["manifest"]
    artifacts = {aid: store.artifact(conn, actor, aid) for aid in dict.fromkeys(
        [obj["artifact_id"], *manifest["dataset_snapshot_ids"], *manifest["gate_input_artifact_ids"].get("6", [])])}
    report: dict[str, Any] = {"checks": dict.fromkeys(("historical_fees", "funding_borrow_known",
        "fill_fidelity", "capacity_stress", "latency_constraints"), False), "hard_invalidity": False,
        "unknowns": [], "metrics": []}
    try:
        plans = [row for row in artifacts.values() if row["schema_name"] == "research/economics-plan-v1"]
        if len(plans) != 1:
            raise UnknownContractError("G6_PLAN_MISSING_OR_AMBIGUOUS")
        plan = EconomicsPlan.model_validate(plans[0]["content"])
        if (plan.candidate_artifact_id != obj["artifact_id"] or plan.candidate_hash != manifest["candidate_hash"]
                or plan.snapshot_id != manifest["snapshot_id"] or plan.code_hash != store.fingerprint
                or plans[0]["created_at"] >= snapshot["created_at"]):
            raise UnknownContractError("G6_PLAN_BINDING_MISMATCH")
        policy_row = artifacts[plan.policy_artifact_id]
        principal = conn.execute("SELECT role FROM principals WHERE principal_id=%s", (policy_row["producer_id"],)).fetchone()
        if (policy_row["schema_name"] != "execution/economics-policy-v1" or not principal
                or principal["role"] not in {"governance", "evaluator"}
                or plan.policy_artifact_id not in manifest["calibration_artifact_ids"]
                or policy_row["created_at"] >= snapshot["created_at"]):
            raise UnknownContractError("G6_UNTRUSTED_OR_UNPINNED_POLICY")
        policy = EconomicsPolicy.model_validate(policy_row["content"])
        if policy.version != manifest["gate_policy_versions"]["6"]:
            raise UnknownContractError("G6_POLICY_VERSION_MISMATCH")
        package_row, g5_decision = _g5(store, conn, actor, obj, artifacts)
        g5 = package_row["content"]
        dataset = artifacts[plan.execution_dataset_artifact_id]
        data_manifest = DatasetManifest.model_validate(dataset["content"])
        persisted = conn.execute("SELECT e.artifact_ids FROM dataset_manifests d JOIN event_log e USING(event_id) "
            "WHERE d.manifest_artifact_id=%s", (dataset["artifact_id"],)).fetchone()
        if (not persisted or dataset["schema_name"] != "data/dataset-manifest-v1"
                or data_manifest.quality_status != QualityStatus.PASS or data_manifest.missing_intervals
                or data_manifest.repair_events or data_manifest.provider_revision_id
                or len(data_manifest.raw_payload_hashes) != 1
                or not data_manifest.end_time <= data_manifest.as_of_time <= data_manifest.fetched_at <= snapshot["created_at"]):
            raise UnknownContractError("G6_DATA_PROVENANCE_UNSUPPORTED")
        payload, metadata = _raw(store, conn, actor, data_manifest.raw_payload_hashes[0], artifacts,
            snapshot["created_at"], persisted["artifact_ids"])
        tape = ExecutionTape.model_validate_json(payload)
        if (data_manifest.content_hash != content_hash(tape.model_dump(mode="json"))
                or data_manifest.schema_hash != content_hash(ExecutionTape.model_json_schema())
                or (data_manifest.venue, data_manifest.instrument) != (tape.venue, tape.instrument_id)
                or data_manifest.instrument_type != "spot" or metadata["provider"] != data_manifest.provider
                or datetime.fromisoformat(metadata["retrieved_at"]) != data_manifest.fetched_at
                or data_manifest.start_time != tape.books[0].event_time or data_manifest.end_time != tape.books[-1].event_time
                or any(row.fidelity.value < data_manifest.fidelity_tier.value for row in tape.books)
                or tape.g5_dataset_artifact_id != g5["configuration"]["dataset_artifact_id"]
                or manifest["dataset_snapshot_ids"] != [tape.g5_dataset_artifact_id]):
            raise UnknownContractError("G6_NORMALIZED_DATA_OR_G5_BINDING_MISMATCH")
        if tape.evidence_kind == "SYNTHETIC":
            raise UnknownContractError("G6_SYNTHETIC_LIQUIDITY_NOT_ECONOMIC_EVIDENCE")
        original_manifest = DatasetManifest.model_validate(artifacts[tape.g5_dataset_artifact_id]["content"])
        original_bytes, _ = _raw(store, conn, actor, original_manifest.raw_payload_hashes[0], artifacts,
            snapshot["created_at"], g5["input_artifacts"])
        original = QuoteReplayData.model_validate_json(original_bytes)
        unit_fields = ("base_currency", "quote_currency", "settlement_currency", "contract_kind", "multiplier")
        if any(any(getattr(rule.specification, field) != getattr(original.instrument, field) for field in unit_fields)
               for rule in tape.rules):
            raise UnknownContractError("G6_G5_ECONOMIC_UNIT_MISMATCH")
        books_by_time = {book.event_time: book for book in tape.books}
        for quote in original.quotes:
            book = books_by_time.get(quote.timestamp)
            if book is None or (book.bids[0].price, book.asks[0].price) != (quote.bid, quote.ask):
                raise UnknownContractError("G6_G5_MARKET_OBSERVATION_CONFLICT")
        calibration = _calibration(store, conn, actor, policy, tape, snapshot, artifacts)
        package = evaluate_economics(g5, tape, policy)
        if canonical(package) != canonical(evaluate_economics(g5, tape, policy)):
            raise UnknownContractError("G6_DETERMINISTIC_REPLAY_DISAGREEMENT")
        package.update(g5_package_artifact_id=package_row["artifact_id"], g5_package_hash=package_row["content_hash"],
            g5_decision_id=g5_decision["gate_decision_id"], g5_snapshot_id=g5_decision["snapshot_id"],
            calibration=calibration, plan=plan.model_dump(mode="json"),
            input_artifacts={aid: row["content_hash"] for aid, row in artifacts.items()})
        aid = store.put_artifact(conn, actor, json.loads(canonical(package)), schema_name="execution/economics-report-v1",
            classification="INTERNAL", policy_version=policy.version)
        artifacts[aid] = store.artifact(conn, actor, aid)
        report.update(package_artifact_id=aid, package_hash=artifacts[aid]["content_hash"],
            checks=package["checks"], hard_invalidity=package["hard_invalidity"], failure_reasons=package["failure_reasons"])
    except ValidationError as error:
        report["unknowns"] = ["G6_INVALID_INPUT:" + ".".join(map(str, item["loc"])) for item in error.errors()]
    except (ValueError, TypeError, ArithmeticError) as error:
        report["unknowns"] = ["G6_EXECUTION_BLOCKED:" + str(error)]
    except DomainError as error:
        report["unknowns"] = ["G6_PROVENANCE_BLOCKED:" + error.code]
    except KeyError:
        report["unknowns"] = ["G6_INPUT_ARTIFACT_MISSING"]
    report["input_artifacts"] = {aid: row["content_hash"] for aid, row in artifacts.items()}
    report["referenced_input_artifacts"] = report["input_artifacts"]
    return report
