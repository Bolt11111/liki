"""DB-backed PAPER execution service; it has no live venue/network adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from psycopg.types.json import Jsonb
from pydantic import Field, field_validator

from liki.core import Contract, DomainError, uid, utcnow
from liki.finance import FeeSchedule, FidelityTier, Fill, FillModel, InstrumentSpec, LedgerState, LiquidityRole, OrderIntent, OrderRecord, OrderState, RiskEnvelope, Side, independently_reconcile, pretrade_check, select_fee
from liki.finance.contracts import effective_at
from liki.finance.execution import MarketSnapshot
from liki.finance.types import decimal
from liki.store import Credential, Store

__all__ = ["DeterministicPaperAdapter", "PaperFill", "PaperRunSpec", "PaperRunStatus", "PaperService", "PinnedFillModel", "StopRequest", "StopScope"]


class PaperRunStatus(StrEnum):
    RECONCILE_ONLY = "RECONCILE_ONLY"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class StopScope(StrEnum):
    GLOBAL = "GLOBAL"
    VENUE = "VENUE"
    STRATEGY = "STRATEGY"


class PinnedFillModel(Contract):
    """The complete, lossless fill-model configuration frozen for one paper run."""

    version: str = Field(min_length=1)
    minimum_fidelity: FidelityTier
    participation_limit: Decimal
    latency_microseconds: int = Field(ge=0)
    queue_assumption: str | None = None
    stress_multiplier: Decimal = Decimal("1")

    @field_validator("participation_limit", "stress_multiplier", mode="before")
    @classmethod
    def _decimal(cls, value: object) -> Decimal:
        return decimal(value)  # type: ignore[arg-type]

    def model_post_init(self, _: object) -> None:
        # Delegate bounds and queue-assumption validation to the execution model itself.
        self.to_fill_model()

    @classmethod
    def from_model(cls, model: FillModel) -> PinnedFillModel:
        return cls(
            version=model.version,
            minimum_fidelity=model.minimum_fidelity,
            participation_limit=model.participation_limit,
            latency_microseconds=model.latency // timedelta(microseconds=1),
            queue_assumption=model.queue_assumption,
            stress_multiplier=model.stress_multiplier,
        )

    def to_fill_model(self) -> FillModel:
        return FillModel(
            version=self.version,
            minimum_fidelity=self.minimum_fidelity,
            participation_limit=self.participation_limit,
            latency=timedelta(microseconds=self.latency_microseconds),
            queue_assumption=self.queue_assumption,
            stress_multiplier=self.stress_multiplier,
        )


class PaperRunSpec(Contract):
    paper_run_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    reporting_currency: str = Field(min_length=1)
    risk_envelope: RiskEnvelope
    fill_model: PinnedFillModel
    instruments: tuple[InstrumentSpec, ...] = Field(min_length=1)
    fee_schedules: tuple[FeeSchedule, ...] = Field(min_length=1)
    fee_account_tier: str = Field(min_length=1)

    def execution_config(self) -> dict:
        return {
            "fill_model": self.fill_model.model_dump(mode="json"),
            "instruments": [item.model_dump(mode="json") for item in self.instruments],
            "fee_schedules": [item.model_dump(mode="json") for item in self.fee_schedules],
            "fee_account_tier": self.fee_account_tier,
        }


class StopRequest(Contract):
    scope: StopScope
    scope_id: str | None = None
    reason_code: str = Field(min_length=1)
    automatic: bool = False
    policy_version: str = Field(default="emergency-stop-v1", min_length=1)

    def model_post_init(self, _: object) -> None:
        if (self.scope == StopScope.GLOBAL) != (self.scope_id is None):
            raise ValueError("GLOBAL stop has no scope id; scoped stops require one")


@dataclass(frozen=True)
class PaperFill:
    external_fill_key: str
    fill_time: datetime
    price: Decimal
    quantity: Decimal
    fee_amount: Decimal
    liquidity_role: LiquidityRole
    execution_model_version: str

    def __post_init__(self) -> None:
        if self.fill_time.tzinfo is None:
            raise ValueError("fill timestamp must be timezone-aware")
        for name in ("price", "quantity", "fee_amount"):
            value = decimal(getattr(self, name))
            object.__setattr__(self, name, value)
        if self.price <= 0 or self.quantity <= 0 or not self.external_fill_key or not self.execution_model_version:
            raise ValueError("invalid paper fill")


class DeterministicPaperAdapter:
    """The sole paper adapter: locally simulated fills, never a network order submission."""

    adapter_name = "deterministic-paper-simulator-v1"

    def simulate(self, intent: OrderIntent, snapshot: MarketSnapshot, model: FillModel) -> PaperFill | None:
        result = model.simulate(intent, snapshot)
        if result is None:
            return None
        return PaperFill(
            external_fill_key=f"SIM:{intent.client_order_id}:{snapshot.timestamp.isoformat()}",
            fill_time=snapshot.timestamp,
            price=result.price,
            quantity=result.quantity,
            fee_amount=Decimal("0"),
            liquidity_role=result.role,
            execution_model_version=model.version,
        )


class PaperService:
    def __init__(self, store: Store, adapter: DeterministicPaperAdapter | None = None):
        self.store = store
        self.adapter = adapter or DeterministicPaperAdapter()

    @staticmethod
    def _lock(conn: object) -> None:
        # Must precede all risk/order reads so competing paper workers serialize by the global lock order.
        conn.execute("SELECT pg_advisory_xact_lock(71403218)")  # type: ignore[attr-defined]

    @staticmethod
    def _prior_operation(
        conn: object, operation_key: str, event_type: str | tuple[str, ...], aggregate_id: str
    ) -> dict | None:
        """Reject key reuse across actions before touching paper projections."""
        event = conn.execute("SELECT * FROM event_log WHERE operation_key=%s", (operation_key,)).fetchone()  # type: ignore[attr-defined]
        if event is None:
            return None
        accepted_types = (event_type,) if isinstance(event_type, str) else event_type
        if event["event_type"] not in accepted_types or event["aggregate_id"] != aggregate_id:
            raise DomainError("IDEMPOTENCY_CONFLICT")
        return event

    def _aggregate(self, conn: object, kind: str, aggregate_id: str) -> dict:
        aggregate = self.store.state(conn, kind, aggregate_id)  # type: ignore[arg-type]
        if aggregate is None:
            raise DomainError("PAPER_PROJECTION_MISSING")
        return aggregate

    def start_run(self, credential: Credential, spec: PaperRunSpec, operation_key: str) -> str:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            existing = conn.execute("SELECT * FROM paper_runs WHERE paper_run_id=%s", (spec.paper_run_id,)).fetchone()
            if existing:
                if self._prior_operation(conn, operation_key, "PAPER_RUN_STARTED_RECONCILE_ONLY", spec.paper_run_id):
                    stored_risk = conn.execute("SELECT content FROM artifacts WHERE artifact_id=%s", (existing["risk_config_artifact_id"],)).fetchone()
                    stored_execution = conn.execute("SELECT content FROM artifacts WHERE artifact_id=%s", (existing["execution_config_artifact_id"],)).fetchone()
                    if stored_risk is None or stored_execution is None:
                        raise DomainError("PAPER_CONFIG_PROJECTION_MISSING")
                    if (existing["policy_version"], existing["reporting_currency"], stored_risk["content"], stored_execution["content"]) != (
                        spec.policy_version, spec.reporting_currency, spec.risk_envelope.model_dump(mode="json"), spec.execution_config()
                    ):
                        raise DomainError("IDEMPOTENCY_CONFLICT")
                    return existing["paper_run_id"]
                raise DomainError("PAPER_RUN_EXISTS")
            risk_artifact = self.store.put_artifact(conn, actor, spec.risk_envelope.model_dump(mode="json"), schema_name="paper/risk-envelope-v1", classification="INTERNAL", policy_version=spec.policy_version)
            execution_artifact = self.store.put_artifact(conn, actor, spec.execution_config(), schema_name="paper/execution-config-v1", classification="INTERNAL", policy_version=spec.policy_version)
            state = {"paper_run_id": spec.paper_run_id, "status": PaperRunStatus.RECONCILE_ONLY, "risk_config_artifact_id": risk_artifact, "execution_config_artifact_id": execution_artifact}
            self.store.transition(conn, actor, capability="paper", kind="paper_run", aggregate_id=spec.paper_run_id, expected_version=0, state=state, event_type="PAPER_RUN_STARTED_RECONCILE_ONLY", operation_key=operation_key, task_id=spec.paper_run_id, policy_version=spec.policy_version, artifact_ids=(risk_artifact, execution_artifact), topic="paper.run")
            conn.execute("INSERT INTO paper_runs(paper_run_id,status,policy_version,risk_config_artifact_id,execution_config_artifact_id,reporting_currency,started_by) VALUES(%s,%s,%s,%s,%s,%s,%s)", (spec.paper_run_id, PaperRunStatus.RECONCILE_ONLY, spec.policy_version, risk_artifact, execution_artifact, spec.reporting_currency, actor.principal_id))
            return spec.paper_run_id

    def reconcile(self, credential: Credential, run_id: str, operation_key: str, *, market_data_valid: bool) -> PaperRunStatus:
        """The required restart barrier; unknown state never becomes active by assumption."""
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            run = conn.execute("SELECT * FROM paper_runs WHERE paper_run_id=%s FOR UPDATE", (run_id,)).fetchone()
            if not run:
                raise DomainError("PAPER_RUN_NOT_FOUND")
            prior = self._prior_operation(conn, operation_key, ("PAPER_RECONCILIATION_COMPLETE", "PAPER_RECONCILIATION_BLOCKED"), run_id)
            if prior:
                recorded = prior["metadata"]["state_after"]
                if recorded.get("market_data_valid") != market_data_valid:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return PaperRunStatus(recorded["status"])
            unresolved = conn.execute("SELECT 1 FROM paper_orders WHERE paper_run_id=%s AND final_state='UNKNOWN_RECONCILING'", (run_id,)).fetchone()
            global_latch = conn.execute(
                "SELECT safety_latch_id FROM paper_safety_latches WHERE active AND scope_type='GLOBAL' FOR UPDATE"
            ).fetchone()
            status = PaperRunStatus.ACTIVE if market_data_valid and not unresolved and not global_latch else PaperRunStatus.RECONCILE_ONLY
            aggregate = self._aggregate(conn, "paper_run", run_id)
            state = {**aggregate["state"], "status": status, "market_data_valid": market_data_valid,
                     "unresolved_orders": bool(unresolved),
                     "global_safety_latch_id": global_latch["safety_latch_id"] if global_latch else None}
            self.store.transition(conn, actor, capability="paper", kind="paper_run", aggregate_id=run_id, expected_version=aggregate["version"], state=state, event_type="PAPER_RECONCILIATION_COMPLETE" if status == PaperRunStatus.ACTIVE else "PAPER_RECONCILIATION_BLOCKED", operation_key=operation_key, task_id=run_id, policy_version=run["policy_version"], topic="paper.reconcile")
            conn.execute("UPDATE paper_runs SET status=%s,reconciled_at=now(),updated_at=now() WHERE paper_run_id=%s", (status, run_id))
            return status

    def restart(self, credential: Credential, run_id: str, operation_key: str) -> PaperRunStatus:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            run = conn.execute("SELECT r.*,a.content AS execution_config FROM paper_runs r JOIN artifacts a ON a.artifact_id=r.execution_config_artifact_id WHERE r.paper_run_id=%s FOR UPDATE OF r", (run_id,)).fetchone()
            if not run:
                raise DomainError("PAPER_RUN_NOT_FOUND")
            if self._prior_operation(conn, operation_key, "PAPER_RESTART_RECONCILE_ONLY", run_id):
                return PaperRunStatus.RECONCILE_ONLY
            aggregate = self._aggregate(conn, "paper_run", run_id)
            self.store.transition(conn, actor, capability="paper", kind="paper_run", aggregate_id=run_id, expected_version=aggregate["version"], state={**aggregate["state"], "status": PaperRunStatus.RECONCILE_ONLY}, event_type="PAPER_RESTART_RECONCILE_ONLY", operation_key=operation_key, task_id=run_id, policy_version=run["policy_version"], topic="paper.reconcile")
            conn.execute("UPDATE paper_runs SET status=%s,updated_at=now() WHERE paper_run_id=%s", (PaperRunStatus.RECONCILE_ONLY, run_id))
            return PaperRunStatus.RECONCILE_ONLY

    def submit(self, credential: Credential, run_id: str, intent: OrderIntent, spec: InstrumentSpec,
               snapshot: MarketSnapshot, envelope: RiskEnvelope, pool_id: str) -> str:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            prior = conn.execute("SELECT * FROM paper_orders WHERE client_order_id=%s", (intent.client_order_id,)).fetchone()
            if prior:
                if prior["intent_json"] != intent.model_dump(mode="json"):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return prior["paper_order_id"]
            run = conn.execute("SELECT r.*,a.content AS execution_config FROM paper_runs r JOIN artifacts a ON a.artifact_id=r.execution_config_artifact_id WHERE r.paper_run_id=%s FOR UPDATE OF r", (run_id,)).fetchone()
            if not run or run["status"] != PaperRunStatus.ACTIVE:
                raise DomainError("PAPER_RECONCILIATION_REQUIRED")
            self._ensure_not_stopped(conn, run_id, intent)
            risk_config = conn.execute("SELECT content FROM artifacts WHERE artifact_id=%s", (run["risk_config_artifact_id"],)).fetchone()
            if risk_config is None:
                raise DomainError("PAPER_CONFIG_PROJECTION_MISSING")
            configured_envelope = risk_config["content"]
            if configured_envelope != envelope.model_dump(mode="json"):
                raise DomainError("RISK_CONFIG_NOT_PINNED")
            configured_spec = self._instrument(run, intent.venue, intent.instrument_id, intent.submission_time)
            if configured_spec.model_dump(mode="json") != spec.model_dump(mode="json"):
                raise DomainError("INSTRUMENT_CONTRACT_MISMATCH")
            position = conn.execute("SELECT quantity FROM paper_positions WHERE paper_run_id=%s AND venue_id=%s AND instrument_id=%s FOR UPDATE", (run_id, intent.venue, intent.instrument_id)).fetchone()
            held = conn.execute("SELECT working_amount,position_amount FROM risk_reservations WHERE paper_run_id=%s AND pool_id=%s AND state IN ('HELD','CONVERTED','UNRECONCILED') FOR UPDATE", (run_id, pool_id)).fetchall()
            active_risk = sum((row["working_amount"] + row["position_amount"] for row in held), Decimal("0"))
            try:
                reservation = pretrade_check(intent, spec, snapshot, envelope, position["quantity"] if position else Decimal("0"), active_risk, utcnow())
            except ValueError as error:
                raise DomainError("PRETRADE_REJECTED", str(error)) from error
            order_id = uid("PORD")
            conn.execute("INSERT INTO risk_reservations(reservation_id,paper_run_id,pool_id,envelope_version,original_amount,working_amount,position_amount,state,expires_at) VALUES(%s,%s,%s,%s,%s,%s,0,'HELD',%s)", (reservation.reservation_id, run_id, pool_id, reservation.envelope_version, reservation.amount, reservation.amount, reservation.expires_at))
            raw = {"adapter": self.adapter.adapter_name, "state_path": ["INTENT", "PRETRADE_VALIDATED", "SUBMITTED", "ACKNOWLEDGED"]}
            conn.execute("INSERT INTO paper_orders(paper_order_id,client_order_id,paper_run_id,strategy_version_id,instrument_id,venue_id,side,order_type,time_in_force,price,quantity,reduce_only,post_only,information_cutoff_time,signal_ready_time,order_eligible_time,decision_time,submitted_time,ack_time,final_state,raw_venue_semantics_json,intent_json,reservation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now(),'ACKNOWLEDGED',%s,%s,%s)", (order_id, intent.client_order_id, run_id, intent.strategy_id, intent.instrument_id, intent.venue, intent.side, intent.order_type, intent.time_in_force, reservation.normalized_limit_price, reservation.normalized_quantity, intent.reduce_only, intent.post_only, intent.information_cutoff_time, intent.signal_ready_time, intent.order_eligible_time, intent.submission_time, Jsonb(raw), Jsonb(intent.model_dump(mode="json")), reservation.reservation_id))
            conn.execute("UPDATE risk_reservations SET paper_order_id=%s,updated_at=now() WHERE reservation_id=%s", (order_id, reservation.reservation_id))
            self.store.transition(conn, actor, capability="paper", kind="paper_order", aggregate_id=order_id, expected_version=0, state={"paper_order_id": order_id, "paper_run_id": run_id, "client_order_id": intent.client_order_id, "state": "ACKNOWLEDGED", "normalized_quantity": str(reservation.normalized_quantity), "reservation_id": reservation.reservation_id}, event_type="PAPER_ORDER_ACKNOWLEDGED", operation_key=f"paper-order:{intent.client_order_id}", task_id=run_id, policy_version=run["policy_version"], topic="paper.order")
            return order_id

    def simulate_order(self, credential: Credential, order_id: str, snapshot: MarketSnapshot, model: FillModel,
                       fee_schedule: FeeSchedule, quote_currency: str) -> str | None:
        """Apply the local simulator's fill through the same idempotent persisted fill path."""
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            order = conn.execute("SELECT * FROM paper_orders WHERE paper_order_id=%s FOR UPDATE", (order_id,)).fetchone()
            if not order:
                raise DomainError("PAPER_ORDER_NOT_FOUND")
            run = conn.execute("SELECT r.*,a.content AS execution_config FROM paper_runs r JOIN artifacts a ON a.artifact_id=r.execution_config_artifact_id WHERE r.paper_run_id=%s", (order["paper_run_id"],)).fetchone()
            if not run:
                raise DomainError("PAPER_EXECUTION_CONFIG_MISSING")
            if self._configured_model(run) != PinnedFillModel.from_model(model):
                raise DomainError("EXECUTION_CONFIG_NOT_PINNED")
            if order["final_state"] in {OrderState.CANCELLED, OrderState.FILLED, OrderState.REJECTED, OrderState.EXPIRED}:
                return None
            intent = OrderIntent.model_validate(order["intent_json"]).model_copy(update={"quantity": order["quantity"], "limit_price": order["price"]})
            simulated = self.adapter.simulate(intent, snapshot, model)
            if simulated is None:
                return None
            instrument = self._instrument(run, order["venue_id"], order["instrument_id"], simulated.fill_time)
            schedule = self._fee_schedule(run, order, simulated)
            if fee_schedule != schedule:
                raise DomainError("FEE_CONFIG_NOT_PINNED")
            calculated = simulated.quantity * simulated.price * instrument.multiplier * schedule.rate
            simulated = replace(simulated, fee_amount=calculated)
        return self.record_fill(credential, order_id, simulated, quote_currency)

    def mark_unknown(self, credential: Credential, order_id: str, reason_code: str, operation_key: str) -> None:
        """Acknowledge transport/reconciliation ambiguity without guessing that an order is absent."""
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            order = conn.execute("SELECT * FROM paper_orders WHERE paper_order_id=%s FOR UPDATE", (order_id,)).fetchone()
            if not order:
                raise DomainError("PAPER_ORDER_NOT_FOUND")
            if self._prior_operation(conn, operation_key, "PAPER_ORDER_UNKNOWN_RECONCILING", order_id):
                existing_reason = self._aggregate(conn, "paper_order", order_id)["state"].get("reconciliation_reason")
                if existing_reason != reason_code:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return
            intent = OrderIntent.model_validate(order["intent_json"]).model_copy(update={"quantity": order["quantity"], "limit_price": order["price"]})
            record = OrderRecord(intent, OrderState(order["final_state"]), order["filled_quantity"]).transition(OrderState.UNKNOWN_RECONCILING, raw_venue_status=reason_code)
            conn.execute("UPDATE paper_orders SET final_state=%s,raw_venue_semantics_json=raw_venue_semantics_json || %s,updated_at=now() WHERE paper_order_id=%s", (record.state, Jsonb({"reconciliation_reason": reason_code}), order_id))
            conn.execute("UPDATE risk_reservations SET state='UNRECONCILED',updated_at=now() WHERE reservation_id=%s", (order["reservation_id"],))
            aggregate = self._aggregate(conn, "paper_order", order_id)
            self.store.transition(conn, actor, capability="paper", kind="paper_order", aggregate_id=order_id, expected_version=aggregate["version"], state={**aggregate["state"], "state": record.state, "reconciliation_reason": reason_code}, event_type="PAPER_ORDER_UNKNOWN_RECONCILING", operation_key=operation_key, task_id=order["paper_run_id"], policy_version=conn.execute("SELECT policy_version FROM paper_runs WHERE paper_run_id=%s", (order["paper_run_id"],)).fetchone()["policy_version"], topic="paper.incident")

    def record_fill(self, credential: Credential, order_id: str, fill: PaperFill, quote_currency: str) -> str:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            existing = conn.execute("SELECT * FROM paper_fills WHERE external_fill_key=%s", (fill.external_fill_key,)).fetchone()
            if existing:
                if (existing["price"], existing["quantity"], existing["fee_amount"], existing["paper_order_id"],
                    existing["fill_time"], existing["fee_asset"], existing["liquidity_flag"], existing["execution_model_version"]) != (
                    fill.price, fill.quantity, fill.fee_amount, order_id, fill.fill_time, quote_currency,
                    fill.liquidity_role, fill.execution_model_version):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return existing["paper_fill_id"]
            order = conn.execute("SELECT * FROM paper_orders WHERE paper_order_id=%s FOR UPDATE", (order_id,)).fetchone()
            if not order:
                raise DomainError("PAPER_ORDER_NOT_FOUND")
            run = conn.execute("SELECT r.*,a.content AS execution_config FROM paper_runs r JOIN artifacts a ON a.artifact_id=r.execution_config_artifact_id WHERE r.paper_run_id=%s", (order["paper_run_id"],)).fetchone()
            if not run:
                raise DomainError("PAPER_EXECUTION_CONFIG_MISSING")
            if fill.execution_model_version != self._configured_model(run).version:
                raise DomainError("EXECUTION_CONFIG_NOT_PINNED")
            instrument = self._instrument(run, order["venue_id"], order["instrument_id"], fill.fill_time)
            if quote_currency != instrument.quote_currency:
                raise DomainError("FILL_QUOTE_CURRENCY_MISMATCH")
            if fill.quantity % instrument.lot_size != 0 or fill.price % instrument.tick_size != 0:
                raise DomainError("FILL_VENUE_INCREMENT_MISMATCH")
            schedule = self._fee_schedule(run, order, fill)
            if fill.fee_amount != fill.quantity * fill.price * instrument.multiplier * schedule.rate:
                raise DomainError("FEE_CONFIG_NOT_PINNED")
            previous_fill = conn.execute("SELECT fill_time FROM paper_fills f JOIN paper_orders o USING(paper_order_id) WHERE o.paper_run_id=%s AND o.venue_id=%s AND o.instrument_id=%s ORDER BY fill_time DESC,fill_sequence DESC LIMIT 1 FOR UPDATE", (order["paper_run_id"], order["venue_id"], order["instrument_id"])).fetchone()
            if previous_fill and fill.fill_time < previous_fill["fill_time"]:
                raise DomainError("FILL_TIME_REGRESSION")
            intent = OrderIntent.model_validate(order["intent_json"]).model_copy(update={"quantity": order["quantity"], "limit_price": order["price"]})
            if fill.fill_time < intent.submission_time:
                raise DomainError("FILL_CAUSALITY_VIOLATION")
            record = OrderRecord(intent, OrderState(order["final_state"]), order["filled_quantity"])
            new_total = record.filled_quantity + fill.quantity
            target = OrderState.FILLED if new_total == record.intent.quantity else OrderState.PARTIALLY_FILLED
            record = record.transition(target, fill_quantity=fill.quantity)
            all_rows = conn.execute("SELECT f.*,o.side,o.client_order_id FROM paper_fills f JOIN paper_orders o USING(paper_order_id) WHERE o.paper_run_id=%s AND o.venue_id=%s AND o.instrument_id=%s ORDER BY f.fill_time,f.fill_sequence FOR UPDATE", (order["paper_run_id"], order["venue_id"], order["instrument_id"])).fetchall()
            ledger = LedgerState(Decimal("0"))
            for row in all_rows:
                ledger.apply(Fill(row["paper_fill_id"], row["client_order_id"], row["fill_time"], Side(row["side"]), row["quantity"], row["price"], LiquidityRole(row["liquidity_flag"]), row["fee_amount"]))
            ledger.apply(Fill(fill.external_fill_key, order["client_order_id"], fill.fill_time, Side(order["side"]), fill.quantity, fill.price, fill.liquidity_role, fill.fee_amount))
            reference = independently_reconcile(Decimal("0"), ledger.fills, fill.price)
            if ledger.position != reference["position"] or ledger.equity(fill.price) != reference["equity"]:
                raise DomainError("ACCOUNTING_DISAGREEMENT")
            sequence = len(conn.execute("SELECT paper_fill_id FROM paper_fills WHERE paper_order_id=%s FOR UPDATE", (order_id,)).fetchall()) + 1
            fill_id = uid("PFILL")
            conn.execute("INSERT INTO paper_fills(paper_fill_id,paper_order_id,fill_sequence,fill_time,price,quantity,fee_amount,fee_asset,liquidity_flag,execution_model_version,external_fill_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (fill_id, order_id, sequence, fill.fill_time, fill.price, fill.quantity, fill.fee_amount, quote_currency, fill.liquidity_role, fill.execution_model_version, fill.external_fill_key))
            conn.execute("INSERT INTO paper_positions(paper_run_id,venue_id,instrument_id,quantity,cash_currency,realized_pnl) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(paper_run_id,venue_id,instrument_id) DO UPDATE SET quantity=EXCLUDED.quantity,cash_currency=EXCLUDED.cash_currency,realized_pnl=EXCLUDED.realized_pnl,updated_at=now()", (order["paper_run_id"], order["venue_id"], order["instrument_id"], ledger.position, quote_currency, ledger.realized_pnl))
            delta = -Side(order["side"]).sign * fill.quantity * fill.price - fill.fee_amount
            prior_cash = conn.execute("SELECT balance_after FROM paper_cash_ledger WHERE paper_run_id=%s AND currency=%s ORDER BY created_at DESC LIMIT 1 FOR UPDATE", (order["paper_run_id"], quote_currency)).fetchone()
            conn.execute("INSERT INTO paper_cash_ledger(paper_cash_entry_id,paper_run_id,paper_fill_id,currency,delta,balance_after) VALUES(%s,%s,%s,%s,%s,%s)", (uid("PCASH"), order["paper_run_id"], fill_id, quote_currency, delta, (prior_cash["balance_after"] if prior_cash else Decimal("0")) + delta))
            reservation = conn.execute("SELECT * FROM risk_reservations WHERE reservation_id=%s FOR UPDATE", (order["reservation_id"],)).fetchone()
            filled_fraction = record.filled_quantity / record.intent.quantity
            position_amount = reservation["original_amount"] * filled_fraction
            conn.execute("UPDATE risk_reservations SET working_amount=%s,position_amount=%s,state=%s,updated_at=now() WHERE reservation_id=%s", (reservation["original_amount"] - position_amount, position_amount, "CONVERTED" if position_amount else "HELD", order["reservation_id"]))
            conn.execute("UPDATE paper_orders SET final_state=%s,filled_quantity=%s,updated_at=now() WHERE paper_order_id=%s", (record.state, record.filled_quantity, order_id))
            aggregate = self._aggregate(conn, "paper_order", order_id)
            self.store.transition(conn, actor, capability="paper", kind="paper_order", aggregate_id=order_id, expected_version=aggregate["version"], state={**aggregate["state"], "state": record.state, "filled_quantity": str(record.filled_quantity), "accounting_check": "PASS"}, event_type="PAPER_FILL_RECORDED", operation_key=f"paper-fill:{fill.external_fill_key}", task_id=order["paper_run_id"], policy_version=conn.execute("SELECT policy_version FROM paper_runs WHERE paper_run_id=%s", (order["paper_run_id"],)).fetchone()["policy_version"], topic="paper.fill")
            return fill_id

    def cancel(self, credential: Credential, order_id: str, operation_key: str) -> None:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("paper")
            self._lock(conn)
            order = conn.execute("SELECT * FROM paper_orders WHERE paper_order_id=%s FOR UPDATE", (order_id,)).fetchone()
            if not order:
                raise DomainError("PAPER_ORDER_NOT_FOUND")
            if self._prior_operation(conn, operation_key, "PAPER_ORDER_CANCELLED", order_id):
                return
            if order["final_state"] == OrderState.CANCELLED:
                raise DomainError("ORDER_ALREADY_CANCELLED")
            if order["final_state"] == OrderState.UNKNOWN_RECONCILING:
                raise DomainError("UNKNOWN_ORDER_REQUIRES_RECONCILIATION")
            intent = OrderIntent.model_validate(order["intent_json"]).model_copy(update={"quantity": order["quantity"], "limit_price": order["price"]})
            state = OrderRecord(intent, OrderState(order["final_state"]), order["filled_quantity"]).transition(OrderState.CANCEL_PENDING).transition(OrderState.CANCELLED)
            reservation = conn.execute("SELECT * FROM risk_reservations WHERE reservation_id=%s FOR UPDATE", (order["reservation_id"],)).fetchone()
            new_state = "CONVERTED" if reservation["position_amount"] > 0 else "RELEASED"
            conn.execute("UPDATE risk_reservations SET working_amount=0,released_amount=%s,state=%s,updated_at=now() WHERE reservation_id=%s", (reservation["original_amount"] - reservation["position_amount"], new_state, reservation["reservation_id"]))
            conn.execute("UPDATE paper_orders SET final_state=%s,updated_at=now() WHERE paper_order_id=%s", (state.state, order_id))
            aggregate = self._aggregate(conn, "paper_order", order_id)
            self.store.transition(conn, actor, capability="paper", kind="paper_order", aggregate_id=order_id, expected_version=aggregate["version"], state={**aggregate["state"], "state": state.state}, event_type="PAPER_ORDER_CANCELLED", operation_key=operation_key, task_id=order["paper_run_id"], policy_version=conn.execute("SELECT policy_version FROM paper_runs WHERE paper_run_id=%s", (order["paper_run_id"],)).fetchone()["policy_version"], topic="paper.order")

    def stop(self, credential: Credential, run_id: str, request: StopRequest, operation_key: str) -> str:
        with self.store.transaction(credential) as (conn, actor):
            if actor.role == "paper" and not request.automatic:
                raise DomainError("MANUAL_STOP_REQUIRES_OWNER")
            if actor.role not in {"paper", "owner", "operator"}:
                raise DomainError("FORBIDDEN")
            self._lock(conn)
            run = conn.execute("SELECT * FROM paper_runs WHERE paper_run_id=%s FOR UPDATE", (run_id,)).fetchone()
            if not run:
                raise DomainError("PAPER_RUN_NOT_FOUND")
            prior = self._prior_operation(conn, operation_key, "PAPER_EMERGENCY_STOP", run_id)
            if prior:
                previous_request = prior["metadata"]["state_after"].get("last_stop")
                if previous_request != request.model_dump(mode="json"):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                existing_stop = conn.execute("SELECT emergency_stop_id FROM emergency_stop_events WHERE event_id=%s", (prior["event_id"],)).fetchone()
                if not existing_stop:
                    raise DomainError("PAPER_STOP_PROJECTION_MISSING")
                return existing_stop["emergency_stop_id"]
            aggregate = self._aggregate(conn, "paper_run", run_id)
            event = self.store.transition(conn, actor, capability="stop", kind="paper_run", aggregate_id=run_id, expected_version=aggregate["version"], state={**aggregate["state"], "last_stop": request.model_dump(mode="json")}, event_type="PAPER_EMERGENCY_STOP", operation_key=operation_key, task_id=run_id, policy_version=run["policy_version"], topic="paper.stop")
            stop_id = uid("STOP")
            conn.execute("INSERT INTO emergency_stop_events(emergency_stop_id,paper_run_id,scope_type,scope_id,reason_code,automatic,actor_id,event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)", (stop_id, run_id, request.scope, request.scope_id, request.reason_code, request.automatic, actor.principal_id, event["event_id"]))
            # Stops block only their declared scope; they never invent a blind market flatten.
            return stop_id

    def emergency_stop(self, credential: Credential, request: StopRequest, operation_key: str) -> str:
        """Durably latch GLOBAL/VENUE stops before cancelling risk-increasing paper orders."""
        if request.scope not in {StopScope.GLOBAL, StopScope.VENUE}:
            raise DomainError("GLOBAL_STOP_SCOPE_REQUIRED")
        with self.store.transaction(credential) as (conn, actor):
            if actor.role == "paper" and not request.automatic:
                raise DomainError("MANUAL_STOP_REQUIRES_OWNER")
            if actor.role not in {"paper", "owner", "operator"}:
                raise DomainError("FORBIDDEN")
            self._lock(conn)
            aggregate_id = request.scope if request.scope == StopScope.GLOBAL else f"VENUE:{request.scope_id}"
            prior = self._prior_operation(conn, operation_key, "PAPER_GLOBAL_EMERGENCY_STOP", aggregate_id)
            if prior:
                state = prior["metadata"]["state_after"]
                if state.get("request") != request.model_dump(mode="json"):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return state["safety_latch_id"]
            active = conn.execute(
                "SELECT safety_latch_id FROM paper_safety_latches WHERE active AND scope_type=%s AND scope_id IS NOT DISTINCT FROM %s FOR UPDATE",
                (request.scope, request.scope_id),
            ).fetchone()
            if active:
                raise DomainError("PAPER_STOP_ALREADY_ACTIVE")
            latch_id = uid("SLATCH")
            state = {"safety_latch_id": latch_id, "request": request.model_dump(mode="json"), "active": True}
            latch_aggregate = self.store.state(conn, "paper_safety_latch", aggregate_id)
            event = self.store.transition(
                conn, actor, capability="stop", kind="paper_safety_latch", aggregate_id=aggregate_id,
                expected_version=latch_aggregate["version"] if latch_aggregate else 0,
                state=state, event_type="PAPER_GLOBAL_EMERGENCY_STOP",
                operation_key=operation_key, task_id=latch_id, policy_version=request.policy_version,
                topic="paper.stop",
            )
            conn.execute(
                "INSERT INTO paper_safety_latches(safety_latch_id,scope_type,scope_id,reason_code,automatic,actor_id,event_id) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (latch_id, request.scope, request.scope_id, request.reason_code, request.automatic, actor.principal_id, event["event_id"]),
            )
            orders = conn.execute(
                "SELECT * FROM paper_orders WHERE final_state IN ('ACKNOWLEDGED','PARTIALLY_FILLED','AMENDED','CANCEL_PENDING') AND NOT reduce_only "
                "AND (%s='GLOBAL' OR venue_id=%s) FOR UPDATE",
                (request.scope, request.scope_id),
            ).fetchall()
            for order in orders:
                self._cancel_for_safety_latch(conn, actor, order, latch_id)
            if request.scope == StopScope.GLOBAL:
                # A global rearm must always start from a newly reconciled account view.
                active_runs = conn.execute("SELECT * FROM paper_runs WHERE status='ACTIVE' FOR UPDATE").fetchall()
                for active_run in active_runs:
                    aggregate = self._aggregate(conn, "paper_run", active_run["paper_run_id"])
                    self.store.transition(
                        conn, actor, capability="stop", kind="paper_run", aggregate_id=active_run["paper_run_id"],
                        expected_version=aggregate["version"],
                        state={**aggregate["state"], "status": PaperRunStatus.RECONCILE_ONLY,
                               "global_safety_latch_id": latch_id},
                        event_type="PAPER_GLOBAL_SAFETY_LATCH_RECONCILIATION_REQUIRED",
                        operation_key=f"safety-latch-fence:{latch_id}:{active_run['paper_run_id']}",
                        task_id=active_run["paper_run_id"], policy_version=active_run["policy_version"],
                        topic="paper.reconcile",
                    )
                    conn.execute(
                        "UPDATE paper_runs SET status=%s,updated_at=now() WHERE paper_run_id=%s",
                        (PaperRunStatus.RECONCILE_ONLY, active_run["paper_run_id"]),
                    )
            return latch_id

    def release_emergency_stop(
        self, credential: Credential, latch_id: str, reason_code: str, operation_key: str
    ) -> None:
        """Owner-only explicit rearm; a released latch never reactivates a paper run."""
        with self.store.transaction(credential) as (conn, actor):
            if actor.role != "owner":
                raise DomainError("STOP_RELEASE_REQUIRES_OWNER")
            self._lock(conn)
            latch = conn.execute(
                "SELECT * FROM paper_safety_latches WHERE safety_latch_id=%s FOR UPDATE", (latch_id,)
            ).fetchone()
            if not latch:
                raise DomainError("PAPER_SAFETY_LATCH_NOT_FOUND")
            aggregate_id = latch["scope_type"] if latch["scope_type"] == StopScope.GLOBAL else f"VENUE:{latch['scope_id']}"
            prior = self._prior_operation(conn, operation_key, "PAPER_GLOBAL_EMERGENCY_STOP_RELEASED", aggregate_id)
            if prior:
                if prior["metadata"]["state_after"].get("safety_latch_id") != latch_id:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return
            if not latch["active"]:
                raise DomainError("PAPER_STOP_NOT_ACTIVE")
            aggregate = self._aggregate(conn, "paper_safety_latch", aggregate_id)
            self.store.transition(
                conn, actor, capability="stop", kind="paper_safety_latch", aggregate_id=aggregate_id,
                expected_version=aggregate["version"],
                state={"safety_latch_id": latch_id, "active": False, "release_reason_code": reason_code},
                event_type="PAPER_GLOBAL_EMERGENCY_STOP_RELEASED", operation_key=operation_key,
                task_id=latch_id, policy_version="emergency-stop-v1", topic="paper.stop",
            )
            conn.execute("UPDATE paper_safety_latches SET active=false WHERE safety_latch_id=%s", (latch_id,))

    def _cancel_for_safety_latch(self, conn: object, actor: object, order: dict, latch_id: str) -> None:
        """Cancel only risk-increasing working orders; reduce-only orders remain available to reduce exposure."""
        reservation = conn.execute("SELECT * FROM risk_reservations WHERE reservation_id=%s FOR UPDATE", (order["reservation_id"],)).fetchone()  # type: ignore[attr-defined]
        if reservation is None:
            raise DomainError("PAPER_RESERVATION_PROJECTION_MISSING")
        new_state = "CONVERTED" if reservation["position_amount"] > 0 else "RELEASED"
        conn.execute("UPDATE risk_reservations SET working_amount=0,released_amount=%s,state=%s,updated_at=now() WHERE reservation_id=%s", (reservation["original_amount"] - reservation["position_amount"], new_state, reservation["reservation_id"]))  # type: ignore[attr-defined]
        conn.execute("UPDATE paper_orders SET final_state='CANCELLED',raw_venue_semantics_json=raw_venue_semantics_json || %s,updated_at=now() WHERE paper_order_id=%s", (Jsonb({"safety_latch_id": latch_id, "cancel_reason": "EMERGENCY_STOP"}), order["paper_order_id"]))  # type: ignore[attr-defined]
        aggregate = self._aggregate(conn, "paper_order", order["paper_order_id"])
        self.store.transition(conn, actor, capability="stop", kind="paper_order", aggregate_id=order["paper_order_id"], expected_version=aggregate["version"], state={**aggregate["state"], "state": "CANCELLED", "cancel_reason": "EMERGENCY_STOP", "safety_latch_id": latch_id}, event_type="PAPER_ORDER_CANCELLED_FOR_SAFETY_LATCH", operation_key=f"safety-latch-cancel:{latch_id}:{order['paper_order_id']}", task_id=order["paper_run_id"], policy_version=conn.execute("SELECT policy_version FROM paper_runs WHERE paper_run_id=%s", (order["paper_run_id"],)).fetchone()["policy_version"], topic="paper.order")  # type: ignore[attr-defined]

    @staticmethod
    def _configured_model(run: dict) -> PinnedFillModel:
        try:
            return PinnedFillModel.model_validate(run["execution_config"]["fill_model"], strict=False)
        except (KeyError, TypeError, ValueError) as error:
            raise DomainError("PAPER_EXECUTION_CONFIG_INVALID") from error

    @staticmethod
    def _instrument(run: dict, venue: str, instrument_id: str, when: datetime) -> InstrumentSpec:
        try:
            instruments = tuple(InstrumentSpec.model_validate(item, strict=False) for item in run["execution_config"]["instruments"])
            return effective_at((item for item in instruments if item.venue == venue and item.instrument_id == instrument_id), when)
        except (KeyError, TypeError, ValueError) as error:
            raise DomainError("INSTRUMENT_CONFIG_NOT_PINNED") from error

    @staticmethod
    def _fee_schedule(run: dict, order: dict, fill: PaperFill) -> FeeSchedule:
        try:
            schedules = tuple(FeeSchedule.model_validate(item, strict=False) for item in run["execution_config"]["fee_schedules"])
            return select_fee(
                schedules,
                venue=order["venue_id"],
                instrument_id=order["instrument_id"],
                account_tier=run["execution_config"]["fee_account_tier"],
                liquidity_role=fill.liquidity_role,
                when=fill.fill_time,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise DomainError("FEE_CONFIG_NOT_PINNED") from error

    @staticmethod
    def _ensure_not_stopped(conn: object, run_id: str, intent: OrderIntent) -> None:
        stopped = conn.execute("SELECT 1 FROM emergency_stop_events WHERE paper_run_id=%s AND active AND (scope_type='GLOBAL' OR (scope_type='VENUE' AND scope_id=%s) OR (scope_type='STRATEGY' AND scope_id=%s))", (run_id, intent.venue, intent.strategy_id)).fetchone()  # type: ignore[attr-defined]
        stopped = stopped or conn.execute("SELECT 1 FROM paper_safety_latches WHERE active AND (scope_type='GLOBAL' OR (scope_type='VENUE' AND scope_id=%s))", (intent.venue,)).fetchone()  # type: ignore[attr-defined]
        if stopped:
            raise DomainError("PAPER_STOP_ACTIVE")
