"""Signed G7 provenance, prospective declarations and conservative trial accounting."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

from liki.backtest_gate import QuoteReplayData
from liki.core import DomainError, canonical, content_hash
from liki.data.models import DatasetManifest, QualityStatus
from liki.finance.economics_contracts import ExecutionTape
from liki.statistics.oos import OOSDeclaration, OOSPlan, OOS_VERSION, evaluate_oos
from liki.store import Identity, Store


def _upstream(store, conn, actor, snapshot, obj, artifacts):
    from liki.verification import verify_execution

    decision = conn.execute("SELECT * FROM gate_decisions WHERE strategy_version_id=%s AND gate_id=6 "
        "AND snapshot_id=%s AND decision='PASS' ORDER BY gate_state_version_after DESC LIMIT 1",
        (obj["object_id"], snapshot["snapshot_id"])).fetchone()
    if not decision or len(decision["evidence_ids"]) != 1:
        raise ValueError("G7_APPLIED_G6_PASS_MISSING_OR_AMBIGUOUS")
    evidence = conn.execute("SELECT artifact_id FROM evidence WHERE evidence_id=%s", (decision["evidence_ids"][0],)).fetchone()
    report = store.artifact(conn, actor, evidence["artifact_id"])
    verify_execution(store, conn, actor, report, SimpleNamespace(snapshot_id=snapshot["snapshot_id"],
        strategy_version_id=obj["object_id"], gate_id=6, expected_version=decision["gate_state_version_before"]), snapshot)
    artifacts[report["artifact_id"]] = report
    package = store.artifact(conn, actor, report["content"]["package_artifact_id"])
    if package["schema_name"] != "execution/economics-report-v1" or package["content_hash"] != report["content"]["package_hash"]:
        raise ValueError("G7_G6_PACKAGE_BINDING_MISMATCH")
    artifacts[package["artifact_id"]] = package
    for aid, digest in package["content"]["input_artifacts"].items():
        source = store.artifact(conn, actor, aid)
        if source["content_hash"] != digest:
            raise ValueError("G7_UPSTREAM_INPUT_BINDING_MISMATCH")
        artifacts[aid] = source
    return package, decision


def _dataset(store, conn, actor, aid, expected_id, model, artifacts, declared_at, snapshot_at):
    artifact = store.artifact(conn, actor, aid)
    artifacts[aid] = artifact
    if artifact["schema_name"] != "data/dataset-manifest-v1":
        raise ValueError("G7_DATASET_SCHEMA_MISMATCH")
    data = DatasetManifest.model_validate(artifact["content"])
    persisted = conn.execute("SELECT * FROM dataset_manifests WHERE manifest_artifact_id=%s", (aid,)).fetchone()
    if (not persisted or data.dataset_snapshot_id != expected_id
            or data.quality_status != QualityStatus.PASS or data.missing_intervals or data.repair_events
            or data.provider_revision_id or data.duplicates_removed or data.bad_ticks_removed
            or data.freshness_sec > data.freshness_sla_sec or len(data.raw_payload_hashes) != 1
            or not declared_at < artifact["created_at"] < snapshot_at
            or not data.end_time <= data.as_of_time <= data.fetched_at <= snapshot_at):
        raise ValueError("G7_PERSISTED_VALIDATION_DATA_REQUIRED")
    raw_hash = data.raw_payload_hashes[0]
    rows = conn.execute("SELECT a.* FROM artifacts a JOIN data_raw_payloads r USING(artifact_id) "
        "WHERE r.content_hash=%s ORDER BY a.created_at", (raw_hash,)).fetchall()
    if not rows or any(row["created_at"] <= declared_at for row in rows):
        raise ValueError("G7_RAW_DATA_PREDATES_DECLARATION_OR_MISSING")
    event = conn.execute("SELECT artifact_ids FROM event_log WHERE event_id=%s", (persisted["event_id"],)).fetchone()
    matching = [row for row in rows if event and row["artifact_id"] in event["artifact_ids"]]
    if len(matching) != 1:
        raise ValueError("G7_RAW_PERSISTENCE_EVENT_BINDING_MISMATCH")
    raw = store.artifact(conn, actor, matching[0]["artifact_id"])
    metadata = raw["content"]["raw_payload"]
    retrieved = datetime.fromisoformat(metadata["retrieved_at"])
    if (metadata.get("provider_revision_id") or metadata["provider"] != data.provider or retrieved != data.fetched_at
            or not declared_at < retrieved <= raw["created_at"] < snapshot_at):
        raise ValueError("G7_RAW_RETRIEVAL_PROVENANCE_MISMATCH")
    artifacts[raw["artifact_id"]] = raw
    payload = base64.b64decode(raw["content"]["payload_base64"], validate=True)
    if "sha256:" + sha256(payload).hexdigest() != raw_hash:
        raise ValueError("G7_RAW_HASH_MISMATCH")
    parsed = model.model_validate_json(payload)
    if data.content_hash != content_hash(parsed.model_dump(mode="json")) or data.schema_hash != content_hash(model.model_json_schema()):
        raise ValueError("G7_NORMALIZED_DATA_MISMATCH")
    return parsed, data


def _trial(conn, declaration, declaration_row, obj, snapshot_at):
    trial = conn.execute("SELECT * FROM trial_events WHERE trial_event_id=%s", (declaration.trial_event_id,)).fetchone()
    if (not trial or trial["infrastructure_retry"] or trial["trial_type"] != "window"
            or trial["strategy_version_id"] != obj["object_id"] or trial["campaign_id"] != obj["campaign_id"]
            or trial["trial_family_id"] != declaration.trial_family_id
            or trial["metadata_json"] != {"g7_declaration_hash": declaration_row["content_hash"]}
            or set(trial["dataset_snapshot_ids"]) != {declaration.quote_dataset_snapshot_id, declaration.execution_dataset_snapshot_id}
            or trial["metric_ids"] != ["net-return", "benchmark-excess", "minimum-fill-ratio"]
            or trial["started_at"] < declaration_row["created_at"]):
        raise ValueError("G7_PREDECLARED_SCIENTIFIC_TRIAL_REQUIRED")
    trials = conn.execute("SELECT t.trial_event_id,t.trial_family_id,t.campaign_id,t.infrastructure_retry,t.contamination_tags,"
        "t.semantic_hash,t.event_id,e.event_hash FROM trial_events t JOIN event_log e USING(event_id) "
        "WHERE t.started_at<%s AND (t.campaign_id=%s OR t.trial_family_id=%s) ORDER BY t.started_at,t.trial_event_id",
        (snapshot_at, obj["campaign_id"], declaration.trial_family_id)).fetchall()
    budget = conn.execute("SELECT statistical_budget FROM campaigns WHERE campaign_id=%s", (obj["campaign_id"],)).fetchone()
    count = sum(not row["infrastructure_retry"] and row["campaign_id"] == obj["campaign_id"] for row in trials)
    if not budget or count > budget["statistical_budget"]:
        raise ValueError("G7_STATISTICAL_TRIAL_BUDGET_EXHAUSTED")
    return trial, {"trial_event_id": trial["trial_event_id"], "trial_family_id": trial["trial_family_id"],
        "campaign_raw_trials": count, "campaign_budget": budget["statistical_budget"],
        "family_raw_trials": sum(not row["infrastructure_retry"] and row["trial_family_id"] == declaration.trial_family_id for row in trials),
        "as_of_snapshot": snapshot_at,
        "remaining_budget": budget["statistical_budget"] - count, "trial_events": trials,
        "effective_trials": {"status": "NOT_ESTIMATED", "reason": "Conservative raw adaptive history; G8 inference not claimed"}}


def check_oos(store: Store, conn: Any, actor: Identity, snapshot: dict, obj: dict) -> dict:
    manifest = snapshot["manifest"]
    artifacts = {aid: store.artifact(conn, actor, aid) for aid in dict.fromkeys(
        [obj["artifact_id"], *manifest["gate_input_artifact_ids"].get("7", [])])}
    report: dict[str, Any] = {"checks": dict.fromkeys(("predeclared_split", "no_tuning_leakage", "purge_embargo", "trial_history_complete"), False),
        "hard_invalidity": False, "unknowns": [], "metrics": []}
    try:
        plans = [row for row in artifacts.values() if row["schema_name"] == "research/oos-plan-v1"]
        if len(plans) != 1:
            raise ValueError("G7_PLAN_MISSING_OR_AMBIGUOUS")
        plan = OOSPlan.model_validate(plans[0]["content"])
        declared = store.artifact(conn, actor, plan.declaration_artifact_id)
        artifacts[declared["artifact_id"]] = declared
        if declared["schema_name"] != "research/oos-declaration-v1":
            raise ValueError("G7_DECLARATION_SCHEMA_MISMATCH")
        declaration = OOSDeclaration.model_validate(declared["content"])
        if (declaration.snapshot_id != snapshot["snapshot_id"] or declaration.candidate_artifact_id != obj["artifact_id"]
                or declaration.candidate_hash != manifest["candidate_hash"] or declaration.code_hash != store.fingerprint
                or manifest["statistical_method_versions"].get("oos") != OOS_VERSION
                or plans[0]["created_at"] >= snapshot["created_at"]):
            raise ValueError("G7_DECLARATION_BINDING_MISMATCH")
        trial, history = _trial(conn, declaration, declared, obj, snapshot["created_at"])
        declared_at = max(declared["created_at"], trial["started_at"], obj["created_at"])
        report["trial_history"] = history
        # Prospective event time prevents already-seen development data being relabelled OOS.
        if not declared_at < declaration.test_start - declaration.interval or declaration.test_end > snapshot["created_at"]:
            raise ValueError("G7_RESULTS_NOT_PROSPECTIVELY_PREDECLARED_OR_NOT_YET_AVAILABLE")
        contract = artifacts[obj["artifact_id"]]["content"]["research_contract"]
        if declaration.event_horizon_seconds < contract["horizon_seconds"]:
            raise ValueError("G7_EVENT_HORIZON_UNDERDECLARED")
        g6_row, decision = _upstream(store, conn, actor, snapshot, obj, artifacts)
        g6 = g6_row["content"]
        g5_row = artifacts[g6["g5_package_artifact_id"]]
        if g5_row["content_hash"] != g6["g5_package_hash"]:
            raise ValueError("G7_G5_PACKAGE_BINDING_MISMATCH")
        original_manifest = DatasetManifest.model_validate(artifacts[g6["plan"]["execution_dataset_artifact_id"]]["content"])
        if (original_manifest.content_hash != declaration.g6_execution_tape_hash
                or artifacts[g6["plan"]["execution_dataset_artifact_id"]]["created_at"] >= declared["created_at"]):
            raise ValueError("G7_EXECUTION_ASSUMPTIONS_NOT_PREDECLARED")
        raw = next(row for row in artifacts.values() if row["schema_name"] == "data/raw-payload-v1"
            and row["content"]["raw_payload"]["content_hash"] == original_manifest.raw_payload_hashes[0])
        development_tape = ExecutionTape.model_validate_json(base64.b64decode(raw["content"]["payload_base64"], validate=True))
        if (raw["created_at"] >= declared["created_at"] or original_manifest.fetched_at >= declared["created_at"]
                or any(book.available_at >= declared["created_at"] for book in development_tape.books)):
            raise ValueError("G7_DEVELOPMENT_EXECUTION_DATA_NOT_YET_AVAILABLE_AT_DECLARATION")
        quotes, quote_manifest = _dataset(store, conn, actor, plan.quote_dataset_artifact_id,
            declaration.quote_dataset_snapshot_id, QuoteReplayData, artifacts, declared_at, snapshot["created_at"])
        tape, tape_manifest = _dataset(store, conn, actor, plan.execution_dataset_artifact_id,
            declaration.execution_dataset_snapshot_id, ExecutionTape, artifacts, declared_at, snapshot["created_at"])
        for data, spec, start, end in ((quote_manifest, quotes.instrument, quotes.quotes[0].timestamp, quotes.quotes[-1].timestamp),
                (tape_manifest, tape.rules[0].specification, tape.books[0].event_time, tape.books[-1].event_time)):
            if ((data.venue, data.instrument, data.instrument_type) != (spec.venue, spec.instrument_id, "spot")
                    or data.start_time != start or data.end_time != end):
                raise ValueError("G7_MARKET_MANIFEST_MISMATCH")
        if (quote_manifest.fidelity_tier.value != "F1_TRADE_BBO"
                or {row.fidelity.value for row in tape.books} != {tape_manifest.fidelity_tier.value}
                or tape.g5_dataset_artifact_id != plan.quote_dataset_artifact_id
                or any(row.available_at > tape_manifest.fetched_at for row in tape.books)):
            raise ValueError("G7_EXECUTION_SOURCE_BINDING_MISMATCH")
        package = evaluate_oos(declaration, g5_row["content"], g6, quotes, tape, development_tape)
        if canonical(package) != canonical(evaluate_oos(declaration, g5_row["content"], g6, quotes, tape, development_tape)):
            raise ValueError("G7_DETERMINISTIC_REPLAY_DISAGREEMENT")
        package.update(g6_package_artifact_id=g6_row["artifact_id"], g6_package_hash=g6_row["content_hash"],
            g6_decision_id=decision["gate_decision_id"], trial_history=history,
            input_artifacts={aid: row["content_hash"] for aid, row in artifacts.items()})
        aid = store.put_artifact(conn, actor, json.loads(canonical(package)), schema_name="validation/oos-report-v1",
            classification="INTERNAL", policy_version=manifest["gate_policy_versions"]["7"])
        artifacts[aid] = store.artifact(conn, actor, aid)
        report.update(package_artifact_id=aid, package_hash=artifacts[aid]["content_hash"],
            checks=package["checks"], hard_invalidity=package["hard_invalidity"], failure_reasons=package["failure_reasons"])
    except ValidationError as error:
        report["unknowns"] = ["G7_INVALID_INPUT:" + ".".join(map(str, item["loc"])) for item in error.errors()]
    except (ValueError, TypeError, ArithmeticError) as error:
        report["unknowns"] = ["G7_EXECUTION_BLOCKED:" + str(error)]
    except DomainError as error:
        report["unknowns"] = ["G7_PROVENANCE_BLOCKED:" + error.code]
    except (KeyError, StopIteration):
        report["unknowns"] = ["G7_INPUT_ARTIFACT_MISSING"]
    report["input_artifacts"] = {aid: row["content_hash"] for aid, row in artifacts.items()}
    report["referenced_input_artifacts"] = report["input_artifacts"]
    return json.loads(canonical(report))
