"""G5 executes a pinned spot protocol from persisted point-in-time quote data."""

from __future__ import annotations

import base64
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from typing import Annotated, Any, Literal

from pydantic import BeforeValidator, Field, ValidationError, field_validator, model_validator

from liki.core import Contract, canonical, content_hash
from liki.data.models import DatasetManifest, QualityStatus, ensure_utc
from liki.finance.backtest import Bar, BacktestResult, CausalHistory, DeterministicBacktest
from liki.finance.contracts import UnknownContractError, effective_at, select_fee
from liki.finance.execution import FillModel, MarketSnapshot
from liki.finance.metrics import expected_shortfall, max_drawdown, simple_returns
from liki.finance.types import ContractKind, FeeSchedule, FidelityTier, InstrumentSpec, LiquidityRole, decimal
from liki.store import Identity, Store

Amount = Annotated[Decimal, BeforeValidator(decimal)]
REPLAY_VERSION = "spot-quote-protocol-v1"


class StrategyProgram(Contract):
    algorithm: Literal["lagged-momentum-v1", "buy-hold-v1"]
    quantity: Amount = Field(gt=0)
    lookback: int = Field(ge=1, le=10000)
    threshold: Amount = Field(ge=0)

    def target(self, history: CausalHistory, when: datetime) -> Decimal:
        if self.algorithm == "buy-hold-v1":
            return self.quantity
        rows = history.all()
        if len(rows) <= self.lookback:
            return Decimal("0")
        change = rows[-1].close / rows[-1 - self.lookback].close - 1
        return self.quantity if change > self.threshold else Decimal("0")


class QuoteObservation(Contract):
    timestamp: datetime
    available_at: datetime
    bid: Amount = Field(gt=0)
    ask: Amount = Field(gt=0)
    executable_quantity: Amount = Field(ge=0)

    _utc = field_validator("timestamp", "available_at")(ensure_utc)

    @model_validator(mode="after")
    def valid_quote(self) -> QuoteObservation:
        if self.ask < self.bid or self.available_at != self.timestamp:
            raise ValueError("protocol requires ordered bid/ask at their actual observation time")
        return self

    def bar(self) -> Bar:
        mid = (self.bid + self.ask) / 2
        return Bar(self.timestamp, mid, mid, mid, mid, self.executable_quantity, self.available_at,
                   FidelityTier.F1_TRADE_BBO, quote=MarketSnapshot(self.timestamp, self.bid, self.ask,
                       self.executable_quantity, FidelityTier.F1_TRADE_BBO))


class KnownFee(Contract):
    schedule: FeeSchedule
    available_at: datetime

    _utc = field_validator("available_at")(ensure_utc)


class QuoteReplayData(Contract):
    schema_version: Literal["spot-quote-tape-v1"]
    instrument: InstrumentSpec
    specification_available_at: datetime
    fees: tuple[KnownFee, ...] = Field(min_length=1)
    quotes: tuple[QuoteObservation, ...] = Field(min_length=2, max_length=10000)
    quantity_semantics: Literal["executable-base-quantity-at-observation"]

    _utc = field_validator("specification_available_at")(ensure_utc)

    @model_validator(mode="after")
    def chronological(self) -> QuoteReplayData:
        times = [quote.timestamp for quote in self.quotes]
        if times != sorted(set(times)):
            raise ValueError("quote tape must be strictly chronological")
        if self.specification_available_at > times[0]:
            raise ValueError("historical instrument specification was not available")
        return self


class ScenarioWindow(Contract):
    name: str = Field(min_length=1, pattern=r"\S")
    start: datetime
    end: datetime

    _utc = field_validator("start", "end")(ensure_utc)

    @model_validator(mode="after")
    def ordered(self) -> ScenarioWindow:
        if self.end <= self.start:
            raise ValueError("scenario requires a positive half-open time interval")
        return self


class ExecutionCosts(Contract):
    version: str = Field(min_length=1)
    slippage_bps: Amount = Field(ge=0)
    impact_bps: Amount = Field(ge=0)
    estimate_reason: str = Field(min_length=1, pattern=r"\S")
    fee: Literal["HISTORICAL_SCHEDULE"]
    spread: Literal["OBSERVED_BBO_EMBEDDED_IN_FILL"]
    funding: Literal["NOT_APPLICABLE_SPOT"]
    borrow: Literal["NOT_APPLICABLE_UNLEVERED_LONG_ONLY"]
    financing: Literal["NOT_APPLICABLE_FULLY_FUNDED"]
    transfer: Literal["NOT_APPLICABLE_SINGLE_VENUE_NO_TRANSFERS"]
    liquidation: Literal["NOT_APPLICABLE_NO_MARGIN"]
    other: Literal["NOT_APPLICABLE_SUPPORTED_PROTOCOL"]


class BacktestPlan(Contract):
    candidate_artifact_id: str = Field(min_length=1)
    candidate_hash: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    dataset_artifact_id: str = Field(min_length=1)
    protocol_version: Literal["spot-quote-protocol-v1"]
    code_hash: str = Field(min_length=1)
    environment_fingerprint: str = Field(min_length=1)
    seed: Literal[0]
    reproducibility: Literal["BITWISE"]
    starting_cash: Amount = Field(gt=0)
    account_tier: str = Field(min_length=1)
    execution_model_version: str = Field(min_length=1)
    participation_limit: Amount = Field(gt=0, le=1)
    latency_seconds: int = Field(ge=0)
    maximum_observation_gap_seconds: int = Field(gt=0)
    costs: ExecutionCosts
    benchmark: StrategyProgram
    tail_confidence: Amount = Field(gt=0, lt=1)
    scenarios: tuple[ScenarioWindow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def benchmark_and_slices(self) -> BacktestPlan:
        if self.benchmark.algorithm != "buy-hold-v1":
            raise ValueError("v1 benchmark must be the simple buy-and-hold challenger")
        if len({item.name for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario names must be unique")
        return self


def _package(result: BacktestResult, plan: BacktestPlan, data: QuoteReplayData) -> dict:
    fills = result.ledger.fills
    equity = [plan.starting_cash] + [value for _, value in result.equity_curve]
    net = equity[-1] - plan.starting_cash
    total_cost = sum(result.cost_totals.values(), Decimal("0"))
    lots: list[list[Any]] = []
    holdings: list[dict] = []
    for fill in fills:
        remaining = fill.quantity
        if fill.side.value == "BUY":
            lots.append([remaining, fill.timestamp])
        else:
            while remaining:
                matched = min(remaining, lots[0][0])
                holdings.append({"quantity": matched, "seconds": Decimal(str((fill.timestamp - lots[0][1]).total_seconds())),
                                 "censored": False})
                remaining -= matched
                lots[0][0] -= matched
                if not lots[0][0]:
                    lots.pop(0)
    holdings.extend({"quantity": quantity, "seconds": Decimal(str((data.quotes[-1].timestamp - start).total_seconds())),
                     "censored": True} for quantity, start in lots)
    scenarios = []
    for window in plan.scenarios:
        indices = [i for i, quote in enumerate(data.quotes) if window.start <= quote.timestamp < window.end]
        if not indices:
            raise UnknownContractError("predeclared scenario has no observations")
        path = equity[indices[0]:indices[-1] + 2]
        scenarios.append({"name": window.name, "start": window.start, "end": window.end,
                          "observations": len(indices), "net_pnl": path[-1] - path[0],
                          "drawdown": max_drawdown(path).model_dump(mode="json")})
    return {"orders": result.orders, "events": result.events,
        "fills": [asdict(fill) for fill in fills], "observations": result.observations,
        "gross_pnl_before_execution_costs": net + total_cost, "net_pnl": net,
        "cost_components": result.cost_totals, "cost_applicability": plan.costs.model_dump(mode="json"),
        "spread_treatment": "EMBEDDED_IN_FILL_NOT_DEDUCTED_TWICE",
        "turnover_notional": sum((fill.quantity * fill.price for fill in fills), Decimal("0")),
        "turnover_over_starting_cash": sum((fill.quantity * fill.price for fill in fills), Decimal("0")) / plan.starting_cash,
        "leverage": [{"timestamp": row["timestamp"], "value": row["exposure"] / row["equity"]
                      if row["equity"] > 0 else None} for row in result.observations],
        "drawdown": max_drawdown(equity).model_dump(mode="json"),
        "tail_loss": expected_shortfall(simple_returns(equity), plan.tail_confidence).model_dump(mode="json"),
        "holding_times": holdings, "scenario_slices": scenarios,
        "market": {"venue": data.instrument.venue, "instrument": data.instrument.instrument_id,
                   "currency": data.instrument.quote_currency},
        "capacity_observations": [{"timestamp": quote.timestamp,
            "model_executable_notional": quote.executable_quantity * plan.participation_limit * (quote.bid + quote.ask) / 2}
            for quote in data.quotes],
        "capacity_limitation": "MODEL_ESTIMATE from observed quote quantity; not validated market impact or capacity curve",
        "rejection_events": result.rejection_events}


def replay(plan: BacktestPlan, data: QuoteReplayData, strategy: StrategyProgram) -> dict:
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        spec = data.instrument
        if (spec.contract_kind != ContractKind.SPOT or spec.multiplier != 1
                or spec.settlement_currency != spec.quote_currency):
            raise UnknownContractError("unsupported derivative or cross-currency replay")
        if any(item.quantity % spec.lot_size or item.quantity < spec.min_quantity
               for item in (strategy, plan.benchmark)):
            raise UnknownContractError("strategy and benchmark targets must use native quantity increments")
        fees = tuple(item.schedule for item in data.fees)
        for index, quote in enumerate(data.quotes):
            effective_at((spec,), quote.timestamp)
            schedule = select_fee(fees, venue=spec.venue, instrument_id=spec.instrument_id,
                                  account_tier=plan.account_tier, liquidity_role=LiquidityRole.TAKER, when=quote.timestamp)
            if any(item.available_at > quote.timestamp for item in data.fees if item.schedule == schedule):
                raise UnknownContractError("historical fee was not available at decision time")
            if index and (quote.timestamp - data.quotes[index - 1].timestamp).total_seconds() > plan.maximum_observation_gap_seconds:
                raise UnknownContractError("market observation gap exceeds protocol")
            if quote.bid % spec.tick_size or quote.ask % spec.tick_size:
                raise UnknownContractError("quote violates native price increment")
        engine = DeterministicBacktest(spec, FillModel(plan.execution_model_version, FidelityTier.F1_TRADE_BBO,
            plan.participation_limit, timedelta(seconds=plan.latency_seconds)), plan.starting_cash,
            fee_schedules=fees, account_tier=plan.account_tier,
            slippage_bps=plan.costs.slippage_bps, impact_bps=plan.costs.impact_bps)
        bars = tuple(quote.bar() for quote in data.quotes)
        candidate = engine.run(bars, target=strategy.target, strategy_id="candidate")
        benchmark = engine.run(bars, target=plan.benchmark.target, strategy_id="benchmark")
        return {"protocol_version": REPLAY_VERSION, "reproducibility": "BITWISE", "seed": plan.seed,
                "arithmetic": {"precision": 28, "rounding": "ROUND_HALF_EVEN", "accounting_tolerance": "0"},
                "configuration": plan.model_dump(mode="json"), "strategy": strategy.model_dump(mode="json"),
                "candidate": _package(candidate, plan, data), "benchmark": _package(benchmark, plan, data)}


def check_backtest(store: Store, conn: Any, actor: Identity, snapshot: dict, obj: dict) -> dict:
    manifest = snapshot["manifest"]
    artifacts = {aid: store.artifact(conn, actor, aid) for aid in dict.fromkeys(
        [obj["artifact_id"], *manifest["dataset_snapshot_ids"], *manifest["gate_input_artifact_ids"].get("5", [])])}
    report: dict[str, Any] = {"checks": dict.fromkeys(("deterministic_replay", "complete_order_ledger",
        "dual_accounting", "all_costs_explicit"), False), "hard_invalidity": False, "unknowns": [], "metrics": []}
    try:
        plans = [row for row in artifacts.values() if row["schema_name"] == "research/backtest-plan-v1"]
        if len(plans) != 1:
            raise UnknownContractError("G5_PLAN_MISSING_OR_AMBIGUOUS")
        plan = BacktestPlan.model_validate(plans[0]["content"])
        if (plan.candidate_artifact_id != obj["artifact_id"] or plan.candidate_hash != manifest["candidate_hash"]
                or plan.snapshot_id != manifest["snapshot_id"] or plans[0]["created_at"] >= snapshot["created_at"]
                or plan.code_hash != store.fingerprint or plan.environment_fingerprint != store.fingerprint
                or manifest["environment_fingerprint"] != store.fingerprint
                or plan.execution_model_version != manifest["execution_model_version"]
                or plan.costs.version != manifest["cost_model_version"]
                or manifest["dataset_snapshot_ids"] != [plan.dataset_artifact_id]):
            raise UnknownContractError("G5_PLAN_BINDING_MISMATCH")
        dataset = artifacts[plan.dataset_artifact_id]
        data_manifest = DatasetManifest.model_validate(dataset["content"])
        persisted = conn.execute("SELECT e.artifact_ids FROM dataset_manifests d JOIN event_log e USING(event_id) "
                                 "WHERE d.manifest_artifact_id=%s", (plan.dataset_artifact_id,)).fetchone()
        if (not persisted or dataset["schema_name"] != "data/dataset-manifest-v1"
                or data_manifest.quality_status != QualityStatus.PASS or data_manifest.missing_intervals
                or data_manifest.repair_events or data_manifest.provider_revision_id
                or not data_manifest.end_time <= data_manifest.as_of_time <= data_manifest.fetched_at <= snapshot["created_at"]
                or len(data_manifest.raw_payload_hashes) != 1):
            raise UnknownContractError("G5_DATA_PROVENANCE_UNSUPPORTED")
        raw_hash = data_manifest.raw_payload_hashes[0]
        raw_rows = conn.execute("SELECT DISTINCT artifact_id FROM data_raw_payloads WHERE content_hash=%s "
                                "AND artifact_id=ANY(%s) ORDER BY artifact_id",
                                (raw_hash, persisted["artifact_ids"])).fetchall()
        if not raw_rows:
            raise UnknownContractError("G5_RAW_DATA_MISSING")
        raw_artifacts = [store.artifact(conn, actor, row["artifact_id"]) for row in raw_rows]
        matching = [row for row in raw_artifacts if row["content"]["raw_payload"]["provider"] == data_manifest.provider]
        if not matching:
            raise UnknownContractError("G5_RAW_PROVIDER_MISMATCH")
        raw = matching[0]
        if raw["created_at"] >= snapshot["created_at"]:
            raise UnknownContractError("G5_RAW_DATA_MUST_PREDATE_EVALUATION")
        if (raw["content"]["raw_payload"].get("provider_revision_id")
                or datetime.fromisoformat(raw["content"]["raw_payload"]["retrieved_at"]) != data_manifest.fetched_at):
            raise UnknownContractError("G5_RAW_RETRIEVAL_PROVENANCE_MISMATCH")
        artifacts[raw["artifact_id"]] = raw
        payload = base64.b64decode(raw["content"]["payload_base64"], validate=True)
        if "sha256:" + sha256(payload).hexdigest() != raw_hash:
            raise UnknownContractError("G5_RAW_HASH_MISMATCH")
        data = QuoteReplayData.model_validate_json(payload)
        if (data_manifest.content_hash != content_hash(data.model_dump(mode="json"))
                or data_manifest.schema_hash != content_hash(QuoteReplayData.model_json_schema())
                or data_manifest.venue != data.instrument.venue or data_manifest.instrument != data.instrument.instrument_id
                or data_manifest.instrument_type != "spot" or data_manifest.fidelity_tier.value != "F1_TRADE_BBO"
                or data_manifest.start_time != data.quotes[0].timestamp or data_manifest.end_time != data.quotes[-1].timestamp):
            raise UnknownContractError("G5_NORMALIZED_DATA_MISMATCH")
        strategy = StrategyProgram.model_validate(artifacts[obj["artifact_id"]]["content"].get("backtest_strategy"))
        package = replay(plan, data, strategy)
        if canonical(package) != canonical(replay(plan, data, strategy)):
            raise UnknownContractError("G5_DETERMINISTIC_REPLAY_DISAGREEMENT")
        bindings = {aid: row["content_hash"] for aid, row in artifacts.items()}
        package["input_artifacts"] = bindings
        aid = store.put_artifact(conn, actor, json.loads(canonical(package)),
            schema_name="backtest/protocol-report-v1", classification="INTERNAL",
            policy_version=manifest["gate_policy_versions"]["5"])
        artifacts[aid] = store.artifact(conn, actor, aid)
        report.update({"package_artifact_id": aid, "package_hash": artifacts[aid]["content_hash"],
                       "checks": dict.fromkeys(report["checks"], True)})
    except ValidationError as error:
        report["unknowns"] = ["G5_INVALID_INPUT:" + ".".join(map(str, item["loc"])) for item in error.errors()]
    except (UnknownContractError, ValueError, TypeError) as error:
        report["unknowns"] = ["G5_REPLAY_BLOCKED:" + str(error)]
    except KeyError:
        report["unknowns"] = ["G5_INPUT_ARTIFACT_MISSING"]
    report["input_artifacts"] = {aid: row["content_hash"] for aid, row in artifacts.items()}
    report["referenced_input_artifacts"] = report["input_artifacts"]
    return report
