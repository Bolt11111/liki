"""Deterministic event backtest with causal data access and fidelity restrictions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from collections.abc import Callable, Sequence

from .accounting import Fill, LedgerState
from .contracts import UnknownContractError, effective_at, fee_amount, rounded_order, select_fee, validate_order
from .execution import FillModel, MarketSnapshot, OrderIntent
from .reference import independently_reconcile
from .types import ContractKind, FeeSchedule, FidelityTier, InstrumentSpec, ReproducibilityTier, Side, decimal, floor_to_increment


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

    def snapshot(self) -> MarketSnapshot:
        if self.fidelity == FidelityTier.F0_BAR:
            # Signals cannot inspect this bar; execution uses its opening observation, not close.
            return MarketSnapshot(self.timestamp, self.open, self.open, self.volume, self.fidelity)
        return MarketSnapshot(self.timestamp, self.open, self.close, self.volume, self.fidelity)


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


@dataclass(frozen=True)
class BacktestResult:
    ledger: LedgerState
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    rejection_events: tuple[str, ...]
    reproducibility: ReproducibilityTier = ReproducibilityTier.BITWISE


class DeterministicBacktest:
    def __init__(self, spec: InstrumentSpec, fill_model: FillModel, starting_cash: Decimal, *,
                 fee_schedules: Sequence[FeeSchedule], account_tier: str):
        if not fee_schedules or not account_tier:
            raise UnknownContractError("backtests require an explicit historical fee policy")
        if (spec.contract_kind != ContractKind.SPOT or spec.multiplier != Decimal("1")
                or spec.settlement_currency != spec.quote_currency):
            raise UnknownContractError("spot ledger cannot value derivative or cross-currency settlement")
        if decimal(starting_cash) <= 0:
            raise ValueError("starting cash must be positive")
        self.spec, self.fill_model, self.starting_cash = spec, fill_model, decimal(starting_cash)
        self.fee_schedules, self.account_tier = tuple(fee_schedules), account_tier

    def run(self, bars: Sequence[Bar], signal: Signal) -> BacktestResult:
        ordered = sorted(bars, key=lambda item: item.timestamp)
        if len({bar.timestamp for bar in ordered}) != len(ordered):
            raise ValueError("duplicate market timestamp")
        if any(bar.revised or bar.timestamp.tzinfo is None or bar.available_at.tzinfo is None
               for bar in ordered):
            raise ValueError("revised or naive market data cannot enter an execution replay")
        ledger = LedgerState(self.starting_cash)
        curve: list[tuple[datetime, Decimal]] = []
        errors: list[str] = []
        for index, bar in enumerate(ordered):
            if bar.available_at > bar.timestamp:
                errors.append(f"unavailable_at_decision:{bar.timestamp.isoformat()}")
                curve.append((bar.timestamp, ledger.equity(bar.close)))
                continue
            intent = signal(CausalHistory(ordered[:index], bar.timestamp), bar.timestamp)
            if intent is not None:
                if intent.signal_ready_time > intent.order_eligible_time or intent.order_eligible_time > intent.submission_time:
                    errors.append(f"causality:{intent.client_order_id}")
                else:
                    try:
                        effective_at((self.spec,), bar.timestamp)
                        if (intent.venue, intent.instrument_id) != (self.spec.venue, self.spec.instrument_id):
                            raise ValueError("order instrument does not match pinned specification")
                        normalized = rounded_order(intent.venue_order(), self.spec)
                        intent = intent.model_copy(update={"quantity": normalized.quantity,
                                                           "limit_price": normalized.limit_price})
                        validate_order(normalized, self.spec, bar.open, ledger.position)
                        simulated = self.fill_model.simulate(intent, bar.snapshot())
                        if simulated is not None:
                            quantity = floor_to_increment(simulated.quantity, self.spec.lot_size)
                            if quantity < self.spec.min_quantity or quantity * simulated.price < self.spec.min_notional:
                                raise ValueError("simulated fill violates native minimum")
                            schedule = select_fee(self.fee_schedules, venue=self.spec.venue,
                                instrument_id=self.spec.instrument_id, account_tier=self.account_tier,
                                liquidity_role=simulated.role, when=bar.timestamp)
                            fee = fee_amount(schedule, quantity * simulated.price).amount
                            if intent.side == Side.BUY and quantity * simulated.price + fee > ledger.cash:
                                raise ValueError("spot purchase exceeds available cash")
                            if intent.side == Side.SELL and quantity > ledger.position:
                                raise ValueError("unfunded spot short requires an explicit borrow model")
                            ledger.apply(Fill(f"{intent.client_order_id}:{index}", intent.client_order_id,
                                bar.timestamp, intent.side, quantity, simulated.price, simulated.role, fee))
                    except UnknownContractError:
                        raise
                    except ValueError as error:
                        errors.append(f"rejected:{intent.client_order_id}:{error}")
            independent = independently_reconcile(self.starting_cash, ledger.fills, bar.close)
            if (ledger.cash != independent["cash"] or ledger.position != independent["position"]
                    or ledger.equity(bar.close) != independent["equity"] or ledger.reconcile(bar.close) != 0):
                raise ValueError("independent accounting disagreement")
            curve.append((bar.timestamp, ledger.equity(bar.close)))
        return BacktestResult(ledger, tuple(curve), tuple(errors))
