"""Deterministic event backtest with causal data access and fidelity restrictions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from collections.abc import Callable, Sequence

from .accounting import CostComponent, CostKind, CostTreatment, Fill, LedgerState
from .contracts import OrderType, TimeInForce, UnknownContractError, effective_at, fee_amount, rounded_order, select_fee, validate_order
from .execution import FillModel, MarketSnapshot, OrderIntent
from .reference import independently_reconcile
from .types import ContractKind, FeeSchedule, FidelityTier, InstrumentSpec, LiquidityRole, ReproducibilityTier, Side, decimal, floor_to_increment


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    available_at: datetime
    fidelity: FidelityTier = FidelityTier.F0_BAR
    revised: bool = False
    quote: MarketSnapshot | None = None

    def __post_init__(self) -> None:
        for name in ("open", "high", "low", "close", "volume"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if (self.low <= 0 or self.volume < 0 or self.low > min(self.open, self.close)
                or self.high < max(self.open, self.close)):
            raise ValueError("invalid market observation")
        if self.quote is not None and (self.quote.timestamp != self.timestamp
                or self.quote.fidelity != self.fidelity):
            raise ValueError("quote must match the observation timestamp and fidelity")

    def snapshot(self) -> MarketSnapshot:
        if self.quote is not None:
            return self.quote
        if self.fidelity == FidelityTier.F0_BAR:
            # Signals cannot inspect this bar; execution uses its opening observation, not close.
            return MarketSnapshot(self.timestamp, self.open, self.open, self.volume, self.fidelity)
        raise UnknownContractError("higher-fidelity replay requires actual bid/ask observations")


class CausalHistory:
    def __init__(self, bars: Sequence[Bar], cutoff: datetime):
        self._bars = tuple(bar for bar in bars if bar.available_at <= cutoff and bar.timestamp <= cutoff and not bar.revised)

    def all(self) -> tuple[Bar, ...]:
        return self._bars

    def latest(self) -> Bar:
        if not self._bars:
            raise ValueError("no point-in-time data at cutoff")
        return self._bars[-1]


Signal = Callable[[CausalHistory, datetime], OrderIntent | None]
Target = Callable[[CausalHistory, datetime], Decimal]


@dataclass(frozen=True)
class BacktestResult:
    ledger: LedgerState
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    rejection_events: tuple[str, ...]
    reproducibility: ReproducibilityTier = ReproducibilityTier.BITWISE
    orders: tuple[dict, ...] = ()
    events: tuple[dict, ...] = ()
    observations: tuple[dict, ...] = ()
    cost_totals: dict[str, Decimal] = field(default_factory=dict)


class DeterministicBacktest:
    def __init__(self, spec: InstrumentSpec, fill_model: FillModel, starting_cash: Decimal, *,
                 fee_schedules: Sequence[FeeSchedule], account_tier: str,
                 slippage_bps: Decimal = Decimal("0"), impact_bps: Decimal = Decimal("0")):
        if not fee_schedules or not account_tier:
            raise UnknownContractError("backtests require an explicit historical fee policy")
        if (spec.contract_kind != ContractKind.SPOT or spec.multiplier != Decimal("1")
                or spec.settlement_currency != spec.quote_currency):
            raise UnknownContractError("spot ledger cannot value derivative or cross-currency settlement")
        if decimal(starting_cash) <= 0:
            raise ValueError("starting cash must be positive")
        self.spec, self.fill_model, self.starting_cash = spec, fill_model, decimal(starting_cash)
        self.fee_schedules, self.account_tier = tuple(fee_schedules), account_tier
        self.slippage_bps, self.impact_bps = decimal(slippage_bps), decimal(impact_bps)
        if min(self.slippage_bps, self.impact_bps) < 0:
            raise ValueError("execution cost bounds cannot be negative")

    def run(self, bars: Sequence[Bar], signal: Signal | None = None, *,
            target: Target | None = None, strategy_id: str = "target") -> BacktestResult:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            return self._run(bars, signal, target=target, strategy_id=strategy_id)

    def _run(self, bars: Sequence[Bar], signal: Signal | None, *,
             target: Target | None, strategy_id: str) -> BacktestResult:
        if (signal is None) == (target is None):
            raise ValueError("exactly one signal or target program is required")
        ordered = sorted(bars, key=lambda item: item.timestamp)
        if not ordered:
            raise ValueError("empty market replay")
        if len({bar.timestamp for bar in ordered}) != len(ordered):
            raise ValueError("duplicate market timestamp")
        if any(bar.revised or bar.timestamp.tzinfo is None or bar.available_at.tzinfo is None
               for bar in ordered):
            raise ValueError("revised or naive market data cannot enter an execution replay")
        ledger = LedgerState(self.starting_cash)
        curve: list[tuple[datetime, Decimal]] = []
        errors: list[str] = []
        orders: dict[str, dict] = {}
        events: list[dict] = []
        observations: list[dict] = []
        pending: dict[str, OrderIntent] = {}
        costs = dict.fromkeys(("fee", "spread", "slippage", "impact"), Decimal("0"))

        def event(order_id: str, timestamp: datetime, state: str, reason: str = "") -> None:
            events.append({"order_id": order_id, "timestamp": timestamp, "state": state, "reason": reason})
            orders[order_id]["state"] = state

        for index, bar in enumerate(ordered):
            if bar.available_at > bar.timestamp:
                errors.append(f"unavailable_at_decision:{bar.timestamp.isoformat()}")
                raise UnknownContractError("execution observation unavailable at simulated time")
            history = CausalHistory(ordered[:index], bar.timestamp)
            intent = signal(history, bar.timestamp) if signal else None
            if target is not None and not pending:
                desired = decimal(target(history, bar.timestamp))
                if desired < 0:
                    raise UnknownContractError("spot target cannot require borrow")
                delta = desired - ledger.position
                if delta:
                    intent = OrderIntent(client_order_id=f"{strategy_id}:{index}", strategy_id=strategy_id,
                        venue=self.spec.venue, instrument_id=self.spec.instrument_id,
                        side=Side.BUY if delta > 0 else Side.SELL, quantity=abs(delta),
                        order_type=OrderType.MARKET, time_in_force=TimeInForce.IOC,
                        information_cutoff_time=bar.timestamp, signal_ready_time=bar.timestamp,
                        order_eligible_time=bar.timestamp, submission_time=bar.timestamp)
            if intent is not None:
                intent = OrderIntent.model_validate(intent.model_dump())
                oid = intent.client_order_id
                if oid in orders:
                    raise ValueError("duplicate client order id")
                orders[oid] = {"intent": intent.model_dump(mode="json"), "state": "INTENT",
                               "filled_quantity": Decimal("0")}
                event(oid, bar.timestamp, "INTENT")
                if (intent.information_cutoff_time > bar.timestamp
                        or intent.submission_time < bar.timestamp
                        or any(item.available_at > intent.information_cutoff_time for item in history.all())):
                    raise ValueError("signal information cutoff does not match causal history")
                pending[oid] = intent
                event(oid, bar.timestamp, "SUBMITTED")
            snapshot = bar.snapshot()
            remaining_liquidity = snapshot.available_quantity * self.fill_model.participation_limit
            for oid, intent in tuple(pending.items()):
                if snapshot.timestamp < intent.submission_time + self.fill_model.latency:
                    continue
                try:
                    effective_at((self.spec,), bar.timestamp)
                    if (intent.venue, intent.instrument_id) != (self.spec.venue, self.spec.instrument_id):
                        raise ValueError("order instrument does not match pinned specification")
                    if self.spec.trading_status != "TRADING":
                        raise ValueError("instrument is not trading")
                    if intent.post_only and intent.order_type == OrderType.MARKET:
                        raise ValueError("post-only market order")
                    if snapshot.fidelity < self.fill_model.minimum_fidelity:
                        raise UnknownContractError("insufficient market-data fidelity for fill model")
                    if self.fill_model.minimum_fidelity == FidelityTier.F0_BAR and intent.order_type != OrderType.MARKET:
                        raise UnknownContractError("OHLC cannot establish passive order fills")
                    normalized = rounded_order(intent.venue_order(), self.spec)
                    intent = intent.model_copy(update={"quantity": normalized.quantity, "limit_price": normalized.limit_price})
                    orders[oid].setdefault("normalized_intent", intent.model_dump(mode="json"))
                    validate_order(normalized, self.spec, bar.open, ledger.position)
                    simulated = self.fill_model.simulate(intent, snapshot)
                    if simulated is not None:
                        if (self.spec.price_lower is not None and simulated.price < self.spec.price_lower
                                or self.spec.price_upper is not None and simulated.price > self.spec.price_upper):
                            raise ValueError("execution price violates venue band")
                        if intent.post_only and simulated.role == LiquidityRole.TAKER:
                            raise ValueError("post-only order would take liquidity")
                        if intent.limit_price is not None and (
                            intent.side == Side.BUY and simulated.price > intent.limit_price
                            or intent.side == Side.SELL and simulated.price < intent.limit_price
                        ):
                            raise ValueError("fill would violate the order limit")
                        if simulated.uncertainty:
                            raise UnknownContractError("passive fill uncertainty requires an explicit queue model")
                        quantity = floor_to_increment(min(simulated.quantity, remaining_liquidity), self.spec.lot_size)
                        if intent.time_in_force == TimeInForce.FOK and quantity < intent.quantity:
                            simulated = None
                        elif quantity < self.spec.min_quantity or quantity * simulated.price < self.spec.min_notional:
                            simulated = None
                    if simulated is not None:
                        notional = quantity * simulated.price
                        slippage = notional * self.slippage_bps / Decimal("10000")
                        impact = notional * self.impact_bps / Decimal("10000")
                        schedule = select_fee(self.fee_schedules, venue=self.spec.venue,
                            instrument_id=self.spec.instrument_id, account_tier=self.account_tier,
                            liquidity_role=simulated.role, when=bar.timestamp)
                        fee = fee_amount(schedule, notional).amount
                        if fee != quantity * simulated.price * schedule.rate:
                            raise UnknownContractError("independent fee accounting disagreement")
                        if ledger.cash - intent.side.sign * notional - fee - slippage - impact < 0:
                            raise ValueError("spot execution costs exceed available cash")
                        if intent.side == Side.SELL and quantity > ledger.position:
                            raise ValueError("unfunded spot short requires an explicit borrow model")
                        ledger.apply(Fill(f"{oid}:{index}", oid, bar.timestamp, intent.side, quantity,
                            simulated.price, simulated.role, fee, (
                                CostComponent(CostKind.IMPLEMENTATION_SHORTFALL, slippage, CostTreatment.ADDITIVE),
                                CostComponent(CostKind.IMPACT, impact, CostTreatment.ADDITIVE))))
                        costs["fee"] += fee
                        costs["slippage"] += slippage
                        costs["impact"] += impact
                        costs["spread"] += quantity * intent.side.sign * (simulated.price - (snapshot.bid + snapshot.ask) / 2)
                        remaining_liquidity -= quantity
                        orders[oid]["filled_quantity"] += quantity
                        event(oid, bar.timestamp, "FILLED" if quantity == intent.quantity else "PARTIALLY_FILLED")
                        if quantity == intent.quantity:
                            del pending[oid]
                        else:
                            pending[oid] = intent.model_copy(update={"quantity": intent.quantity - quantity})
                    if oid in pending and intent.time_in_force in {TimeInForce.IOC, TimeInForce.FOK}:
                        event(oid, bar.timestamp, "CANCELLED", "UNFILLED_IMMEDIATE_REMAINDER")
                        del pending[oid]
                except UnknownContractError:
                    raise
                except ValueError as error:
                    errors.append(f"rejected:{oid}:{error}")
                    event(oid, bar.timestamp, "REJECTED", str(error))
                    del pending[oid]
            independent = independently_reconcile(self.starting_cash, ledger.fills, bar.close)
            if (ledger.cash != independent["cash"] or ledger.position != independent["position"]
                    or ledger.equity(bar.close) != independent["equity"] or ledger.reconcile(bar.close) != 0):
                raise ValueError("independent accounting disagreement")
            curve.append((bar.timestamp, ledger.equity(bar.close)))
            observations.append({"timestamp": bar.timestamp, "mark": bar.close, "cash": ledger.cash,
                "position": ledger.position, "equity": ledger.equity(bar.close),
                "exposure": ledger.position * bar.close, "fees": ledger.fees,
                "other_costs": ledger.other_costs, "reference": independent})
        for oid in pending:
            event(oid, ordered[-1].timestamp, "CANCELLED", "END_OF_REPLAY")
        return BacktestResult(ledger, tuple(curve), tuple(errors), orders=tuple(orders.values()),
                              events=tuple(events), observations=tuple(observations), cost_totals=costs)
