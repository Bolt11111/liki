"""Independent G6 execution counterfactuals over immutable G5 order intents."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Context, Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext
from typing import Any

from .accounting import Fill, LedgerState
from .contracts import UnknownContractError, effective_at, select_fee
from .economics_contracts import BookObservation, EconomicsPolicy, ExecutionTape, VenueRule
from .execution import OrderIntent
from .execution_reference import fee_reference, latency_reference, sweep_reference
from .reference import independently_reconcile
from .types import ContractKind, LiquidityRole, Side

ZERO = Decimal("0")
ONE = Decimal("1")
VERSION = "depth-execution-economics-v1"


def sweep(*, levels, requested, maximum_quantity, lot_size, tick_size, fee_increment,
          fee_rate, impact_bps, traded_quantity, side) -> list[dict]:
    limit = min(requested, maximum_quantity, sum((quantity for _, quantity in levels), ZERO))
    remaining = (limit / lot_size).to_integral_value(rounding=ROUND_FLOOR) * lot_size
    allocated = []
    for price, available in levels:
        quantity = (min(available, remaining) / lot_size).to_integral_value(rounding=ROUND_FLOOR) * lot_size
        if quantity:
            allocated.append((price, quantity))
            remaining -= quantity
    total = sum((quantity for _, quantity in allocated), ZERO)
    if not total:
        return []
    if traded_quantity <= 0:
        raise UnknownContractError("PARTICIPATION_VOLUME_UNAVAILABLE")
    sign = ONE if side == "BUY" else -ONE
    adjustment = impact_bps * (total / traded_quantity).sqrt() / Decimal("10000")
    fills = []
    for raw_price, quantity in allocated:
        price = raw_price * (1 + sign * adjustment)
        price = (price / tick_size).to_integral_value(rounding=ROUND_CEILING if sign > 0 else ROUND_FLOOR) * tick_size
        if price <= 0:
            raise UnknownContractError("IMPACT_MODEL_OUTSIDE_POSITIVE_PRICE_DOMAIN")
        fee = (price * quantity * fee_rate / fee_increment).to_integral_value(rounding=ROUND_CEILING) * fee_increment
        fills.append({"raw_price": raw_price, "price": price, "quantity": quantity, "fee": fee})
    return fills


def _rule(tape: ExecutionTape, when: datetime) -> VenueRule:
    spec = effective_at((row.specification for row in tape.rules), when)
    matches = [row for row in tape.rules if row.specification == spec and row.available_at <= when]
    if len(matches) != 1:
        raise UnknownContractError("EFFECTIVE_VENUE_METADATA_UNKNOWN_OR_CONFLICTING")
    if (spec.contract_kind != ContractKind.SPOT or spec.multiplier != 1
            or spec.settlement_currency != spec.quote_currency):
        raise UnknownContractError("G6_REQUIRES_EXPLICIT_DERIVATIVE_BORROW_OR_FX_PROTOCOL")
    return matches[0]


def _book(tape: ExecutionTape, when: datetime, market_data_ms: int, policy: EconomicsPolicy,
          *, venue_state: bool = False) -> BookObservation:
    cutoff = when - timedelta(milliseconds=market_data_ms)
    visible = [row for row in tape.books if row.event_time <= cutoff and (venue_state or row.available_at <= cutoff)]
    if not visible:
        raise UnknownContractError("EXECUTION_OBSERVATION_UNAVAILABLE")
    book = visible[-1]
    if book.fidelity.value not in {"F2_AGG_L2", "F3_SEQ_L2"}:
        raise UnknownContractError("EXECUTION_FIDELITY_UNSUPPORTED_FOR_DEPTH_PROTOCOL")
    if book.fidelity.value < policy.minimum_fidelity:
        raise UnknownContractError("EXECUTION_FIDELITY_INSUFFICIENT")
    if book.sequence_status == "GAP" or book.fidelity.value >= "F3_SEQ_L2" and book.sequence_status != "VALIDATED":
        raise UnknownContractError("EXECUTION_SEQUENCE_NOT_VALIDATED")
    return book


def _fee(tape: ExecutionTape, when: datetime):
    states = [row for row in tape.account_tiers if row.effective_from <= when
              and (row.effective_to is None or when < row.effective_to)]
    if len(states) != 1 or states[0].available_at > when:
        raise UnknownContractError("HISTORICAL_ACCOUNT_TIER_UNKNOWN_OR_CONFLICTING")
    schedule = select_fee((row.schedule for row in tape.fees), venue=tape.venue,
        instrument_id=tape.instrument_id, account_tier=states[0].tier,
        liquidity_role=LiquidityRole.TAKER, when=when)
    if not any(row.schedule == schedule and row.available_at <= when for row in tape.fees):
        raise UnknownContractError("HISTORICAL_FEE_NOT_AVAILABLE")
    return schedule, states[0]


def _submission_permissions(scheduled, tape, policy, terminal_time):
    events: list[tuple[datetime, int, int]] = []
    for arrival, index, _, sample, sent in scheduled:
        events.extend(((arrival + timedelta(milliseconds=sample.acknowledgement_ms), 0, index),
            (sent + timedelta(milliseconds=policy.acknowledgement_timeout_ms), 1, index), (sent, 2, index)))
    submitted, acknowledged, unknown = set(), set(), set()
    messages: list[datetime] = []
    reasons = {}
    for when, kind, index in sorted(events):
        if kind == 0:
            acknowledged.add(index)
            unknown.discard(index)
        elif kind == 1:
            if index in submitted and index not in acknowledged:
                unknown.add(index)
        elif when <= terminal_time:
            rule = _rule(tape, when)
            count = sum(time > when - timedelta(milliseconds=rule.message_window_ms) for time in messages)
            if unknown:
                reasons[index] = "UNKNOWN_ACK_RECONCILE_ONLY"
            elif count >= rule.message_limit:
                reasons[index] = "VENUE_MESSAGE_RATE_LIMIT"
            else:
                submitted.add(index)
                messages.append(when)
    return reasons


def _case(orders: list[dict], starting_cash: Decimal, terminal_time: datetime, tape: ExecutionTape,
          policy: EconomicsPolicy, scale: Decimal, rotation: int, adverse: bool, impact_bps: Decimal) -> dict:
    ledger = LedgerState(starting_cash)
    intents = [OrderIntent.model_validate(row["intent"]) for row in orders]
    if len({row.client_order_id for row in intents}) != len(intents):
        raise UnknownContractError("DUPLICATE_G5_ORDER_INTENT")
    scheduled = []
    for index, intent in enumerate(intents):
        if intent.order_type.value != "MARKET" or intent.post_only or intent.time_in_force.value != "IOC":
            raise UnknownContractError("PASSIVE_OR_WORKING_ORDER_REQUIRES_QUEUE_AND_CANCEL_PROTOCOL")
        sample = tape.latency_samples[(rotation + index) % len(tape.latency_samples)]
        sent = max(intent.submission_time, intent.signal_ready_time + timedelta(
            milliseconds=sample.market_data_ms + sample.signal_ms + sample.decision_ms))
        arrival = sent + timedelta(milliseconds=sample.network_ms)
        if (sent, arrival) != latency_reference(intent.model_dump(), sample.model_dump()):
            raise UnknownContractError("INDEPENDENT_EXECUTION_LATENCY_DISAGREEMENT")
        scheduled.append((arrival, index, intent, sample, sent))
    scheduled.sort(key=lambda row: (row[0], row[1]))
    submission_rejections = _submission_permissions(scheduled, tape, policy, terminal_time)
    participation_used: dict[datetime, Decimal] = {}
    depth_used: dict[tuple, Decimal] = {}
    records, fills, points = [], [], []
    costs = dict.fromkeys(("fee", "spread", "depth_slippage", "endogenous_impact", "timing", "implementation_shortfall"), ZERO)
    depth_fraction = policy.adverse_depth_fraction if adverse else policy.displayed_depth_fraction
    reference_cash, reference_position = starting_cash, ZERO
    requested_total, filled_total = ZERO, ZERO
    for arrival, index, intent, sample, sent in scheduled:
        if (intent.venue, intent.instrument_id) != (tape.venue, tape.instrument_id):
            raise UnknownContractError("G5_EXECUTION_INSTRUMENT_MISMATCH")
        rule = _rule(tape, min(arrival, terminal_time))
        spec = rule.specification
        quantity = ((intent.quantity * scale) / spec.lot_size).to_integral_value(rounding=ROUND_FLOOR) * spec.lot_size
        requested_total += intent.quantity * scale
        record: dict[str, Any] = {"order_id": intent.client_order_id, "requested_quantity": intent.quantity * scale,
            "normalized_quantity": quantity, "filled_quantity": ZERO, "state": "REJECTED", "reason": "",
            "side": intent.side.value,
            "sent_at": sent, "arrival_at": arrival, "latency_sample_id": sample.sample_id,
            "venue_rule_version": spec.version}
        records.append(record)
        if arrival > terminal_time:
            record.update(state="CANCELLED", reason="LATENCY_BEYOND_EVALUATION_WINDOW")
            continue
        if index in submission_rejections:
            record["reason"] = submission_rejections[index]
            continue
        book = _book(tape, arrival, 0, policy, venue_state=True)
        visible_book = _book(tape, sent, sample.market_data_ms, policy)
        decision_book = _book(tape, intent.information_cutoff_time, 0, policy)
        decision_mid = (decision_book.bids[0].price + decision_book.asks[0].price) / 2
        arrival_mid = (book.bids[0].price + book.asks[0].price) / 2
        schedule, tier = _fee(tape, arrival)
        reference_fee = fee_reference(fees=[row.model_dump() for row in tape.fees],
            tiers=[row.model_dump() for row in tape.account_tiers], venue=tape.venue,
            instrument_id=tape.instrument_id, when=arrival)
        if reference_fee != {"fee_version": schedule.version, "rate": schedule.rate, "account_tier": tier.tier}:
            raise UnknownContractError("INDEPENDENT_EXECUTION_FEE_SELECTION_DISAGREEMENT")
        record.update(fee_version=schedule.version, account_tier=tier.tier, tier_basis=tier.basis,
                      book_event_time=book.event_time, decision_benchmark=decision_mid)
        if book.outage or spec.trading_status != "TRADING":
            record["reason"] = "VENUE_OUTAGE_OR_NOT_TRADING"
        elif max((arrival - book.event_time).total_seconds(), (sent - visible_book.event_time).total_seconds()) * 1000 > policy.stale_after_ms:
            record["reason"] = "STALE_MARKET_DATA"
        elif "MARKET" not in rule.supported_order_types:
            record["reason"] = "UNSUPPORTED_ORDER_TYPE"
        elif quantity < spec.min_quantity or spec.max_quantity is not None and quantity > spec.max_quantity:
            record["reason"] = "NATIVE_QUANTITY_FILTER"
        elif intent.side == Side.SELL and quantity > ledger.position:
            record["reason"] = "SPOT_BORROW_NOT_AVAILABLE"
        elif intent.side == Side.BUY and ledger.position + quantity > rule.max_position_quantity:
            record["reason"] = "POSITION_LIMIT"
        if record["reason"]:
            continue
        levels = book.asks if intent.side == Side.BUY else book.bids
        available = tuple((level.price, max(ZERO, level.quantity * depth_fraction - depth_used.get(
            (intent.side, level.price), ZERO))) for level in levels)
        budget = max(ZERO, book.traded_quantity * policy.participation_limit - participation_used.get(book.event_time, ZERO))
        arguments = dict(levels=available, requested=quantity, maximum_quantity=budget,
            lot_size=spec.lot_size, tick_size=spec.tick_size, fee_increment=rule.fee_increment,
            fee_rate=schedule.rate, impact_bps=impact_bps, traded_quantity=book.traded_quantity,
            side=intent.side.value)
        matched = sweep(**arguments)
        independent = sweep_reference(**arguments)
        if matched != independent:
            raise UnknownContractError("INDEPENDENT_EXECUTION_COST_DISAGREEMENT")
        if not matched:
            record.update(state="CANCELLED", reason="NO_NATIVE_EXECUTABLE_LIQUIDITY")
            continue
        worst_price = max(row["price"] for row in matched)
        notional = sum((row["price"] * row["quantity"] for row in matched), ZERO)
        total_fee = sum((row["fee"] for row in matched), ZERO)
        sign = ONE if intent.side == Side.BUY else -ONE
        if quantity * worst_price > rule.max_order_notional:
            record["reason"] = "ORDER_NOTIONAL_LIMIT"
        elif notional < spec.min_notional:
            record["reason"] = "MINIMUM_NOTIONAL"
        elif any(spec.price_lower is not None and row["price"] < spec.price_lower
                 or spec.price_upper is not None and row["price"] > spec.price_upper for row in matched):
            record["reason"] = "EXECUTION_PRICE_BAND"
        elif max(abs(row["price"] / decision_mid - 1) * 10000 for row in matched) > rule.max_price_deviation_bps:
            record["reason"] = "PRICE_DEVIATION_LIMIT"
        elif ledger.cash - sign * notional - total_fee < 0:
            record["reason"] = "FULLY_FUNDED_CASH_LIMIT"
        if record["reason"]:
            continue
        for fill_index, (row, oracle) in enumerate(zip(matched, independent, strict=True)):
            fill_id = f"{intent.client_order_id}:{fill_index}"
            ledger.apply(Fill(fill_id, intent.client_order_id, arrival, intent.side,
                              row["quantity"], row["price"], LiquidityRole.TAKER, row["fee"]))
            reference_cash -= sign * oracle["quantity"] * oracle["price"] + oracle["fee"]
            reference_position += sign * oracle["quantity"]
            q = row["quantity"]
            best = levels[0].price
            components = {"fee": row["fee"], "spread": sign * (best - arrival_mid) * q,
                "depth_slippage": sign * (row["raw_price"] - best) * q,
                "endogenous_impact": sign * (row["price"] - row["raw_price"]) * q,
                "timing": sign * (arrival_mid - decision_mid) * q,
                "implementation_shortfall": sign * (row["price"] - decision_mid) * q + row["fee"]}
            if components["implementation_shortfall"] != sum((v for k, v in components.items() if k != "implementation_shortfall"), ZERO):
                raise UnknownContractError("COST_DECOMPOSITION_DISAGREEMENT")
            for name, value in components.items():
                costs[name] += value
            fills.append({**row, "fill_id": fill_id, "order_id": intent.client_order_id,
                "side": intent.side.value, "timestamp": arrival, "components": components})
            # A repeated standing-depth snapshot is not evidence of replenishment.
            key = (intent.side, row["raw_price"])
            depth_used[key] = depth_used.get(key, ZERO) + q
            participation_used[book.event_time] = participation_used.get(book.event_time, ZERO) + q
            record["filled_quantity"] += q
            filled_total += q
        reference = independently_reconcile(starting_cash, ledger.fills, arrival_mid)
        if (ledger.cash != reference_cash or ledger.position != reference_position or ledger.cash != reference["cash"]
                or ledger.position != reference["position"] or abs(ledger.reconcile(arrival_mid)) > rule.fee_increment):
            raise UnknownContractError("INDEPENDENT_EXECUTION_ACCOUNTING_DISAGREEMENT")
        acknowledgement = arrival + timedelta(milliseconds=sample.acknowledgement_ms)
        record.update(state="FILLED" if record["filled_quantity"] == quantity else "PARTIALLY_FILLED_CANCELLED",
            acknowledged_at=acknowledgement, cancel_confirmed_at=acknowledgement + timedelta(milliseconds=sample.cancel_ms),
            acknowledgement_state="UNKNOWN_RECONCILING" if acknowledgement > sent + timedelta(
                milliseconds=policy.acknowledgement_timeout_ms) else "ACKNOWLEDGED")
        points.append({"timestamp": arrival, "cash": ledger.cash, "position": ledger.position,
                       "equity": ledger.equity(arrival_mid), "independent": reference})
    final_book = _book(tape, terminal_time, 0, policy, venue_state=True)
    if (terminal_time - final_book.event_time).total_seconds() * 1000 > policy.stale_after_ms:
        raise UnknownContractError("TERMINAL_VALUATION_STALE")
    mark = (final_book.bids[0].price + final_book.asks[0].price) / 2
    net = ledger.equity(mark) - starting_cash
    if net != reference_cash + reference_position * mark - starting_cash:
        raise UnknownContractError("TERMINAL_ACCOUNTING_DISAGREEMENT")
    for record in records:
        record["unfilled_quantity"] = record["requested_quantity"] - record["filled_quantity"]
        record["opportunity_shortfall_diagnostic"] = ((1 if record["side"] == "BUY" else -1)
            * (mark - record["decision_benchmark"]) * record["unfilled_quantity"]
            if "decision_benchmark" in record else None)
    return {"orders": records, "fills": fills, "ledger": points, "cash": ledger.cash,
        "position": ledger.position, "terminal_mark": mark, "net_pnl": net, "net_return": net / starting_cash,
        "gross_decision_price_pnl": net + costs["implementation_shortfall"], "costs": costs,
        "fill_ratio": filled_total / requested_total if requested_total else ZERO,
        "requested_quantity": requested_total, "filled_quantity": filled_total,
        "requested_notional": sum((r["requested_quantity"] * r.get("decision_benchmark", mark) for r in records), ZERO),
        "turnover": sum((fill["price"] * fill["quantity"] for fill in fills), ZERO),
        "rejection_count": sum(row["state"] == "REJECTED" for row in records),
        "partial_fill_count": sum(row["state"] == "PARTIALLY_FILLED_CANCELLED" for row in records)}


def evaluate_economics(g5: dict, tape: ExecutionTape, policy: EconomicsPolicy) -> dict:
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        previous_sequence = None
        for book in tape.books:
            spec = _rule(tape, book.event_time).specification
            if book.fidelity.value == "F3_SEQ_L2":
                if (book.sequence_start is None or book.sequence_end is None
                        or previous_sequence is not None and book.sequence_start != previous_sequence + 1):
                    raise UnknownContractError("G6_SEQUENCE_EVIDENCE_MISSING_OR_DISCONTINUOUS")
                previous_sequence = book.sequence_end
            else:
                previous_sequence = None
            if (spec.quote_currency, spec.settlement_currency) != (g5["candidate"]["market"]["currency"],) * 2:
                raise UnknownContractError("G6_G5_ECONOMIC_UNIT_MISMATCH")
            if any(level.price % spec.tick_size for level in book.bids + book.asks):
                raise UnknownContractError("G6_OBSERVED_PRICE_OFF_NATIVE_TICK")
        if any((b.event_time - a.event_time).total_seconds() * 1000 > policy.max_gap_ms
               or b.volume_window_start < a.event_time for a, b in zip(tape.books, tape.books[1:], strict=False)):
            raise UnknownContractError("G6_GAP_OR_OVERLAPPING_PARTICIPATION_WINDOWS")
        terminal = datetime.fromisoformat(g5["candidate"]["observations"][-1]["timestamp"])
        starting_cash = Decimal(g5["configuration"]["starting_cash"])
        scenarios = []
        workload = (len(g5["candidate"]["orders"]) + len(g5["benchmark"]["orders"])) * len(tape.latency_samples) * len(policy.size_multipliers) * 6
        if workload > 2000000:
            raise UnknownContractError("G6_REPLAY_BUDGET_EXCEEDED")
        rotations = range(len(tape.latency_samples))
        for scale in policy.size_multipliers:
            for rotation in rotations:
                for adverse in (False, True):
                    for bound in ("lower_bps", "central_bps", "upper_bps"):
                        coefficient = getattr(policy.impact, bound)
                        candidate = _case(g5["candidate"]["orders"], starting_cash, terminal, tape, policy, scale, rotation, adverse, coefficient)
                        benchmark = _case(g5["benchmark"]["orders"], starting_cash, terminal, tape, policy, scale, rotation, adverse, coefficient)
                        scenarios.append({"size_multiplier": scale, "latency_rotation": rotation, "adverse_fill": adverse,
                            "impact_bound": bound, "candidate": candidate, "benchmark": benchmark,
                            "excess_return": candidate["net_return"] - benchmark["net_return"]})
        curve = []
        for scale in policy.size_multipliers:
            group = [row for row in scenarios if row["size_multiplier"] == scale]
            curve.append({"size_multiplier": scale,
                "requested_notional_range": [min(x["candidate"]["requested_notional"] for x in group), max(x["candidate"]["requested_notional"] for x in group)],
                "net_return_range": [min(x["candidate"]["net_return"] for x in group), max(x["candidate"]["net_return"] for x in group)],
                "excess_return_range": [min(x["excess_return"] for x in group), max(x["excess_return"] for x in group)],
                "minimum_fill_ratio": min(x["candidate"]["fill_ratio"] for x in group),
                "maximum_rejection_count": max(x["candidate"]["rejection_count"] for x in group)})
        intended = next(row for row in curve if row["size_multiplier"] == 1)
        checks = {"historical_fees": True, "funding_borrow_known": True, "fill_fidelity": True,
                  "capacity_stress": True, "latency_constraints": True}
        failures = []
        if intended["net_return_range"][0] < policy.minimum_worst_net_return:
            failures.append("G6_AFTER_FRICTION_EDGE_FAILED")
        if intended["excess_return_range"][0] < policy.minimum_worst_excess_return:
            failures.append("G6_SIMPLE_BENCHMARK_FAILED")
        if intended["minimum_fill_ratio"] < policy.minimum_fill_ratio:
            failures.append("G6_EXECUTABLE_CAPACITY_FAILED")
        latency = {}
        for field in ("signal_ms", "decision_ms", "network_ms", "acknowledgement_ms", "cancel_ms", "market_data_ms"):
            values = sorted(getattr(row, field) for row in tape.latency_samples)
            latency[field] = {str(p): values[max(0, (len(values) * p + 99) // 100 - 1)] for p in (50, 95, 99)}
        return {"protocol_version": VERSION, "checks": checks, "hard_invalidity": bool(failures),
            "failure_reasons": failures, "unknowns": [], "capacity_curve": curve, "scenarios": scenarios,
            "latency_percentiles": latency, "policy": policy.model_dump(mode="json"),
            "reproducibility": "BITWISE", "arithmetic": {"precision": 50, "rounding": "ROUND_HALF_EVEN",
                "fee_rounding": "CEILING_TO_VENUE_INCREMENT", "accounting_tolerance": "venue fee increment; predeclared"},
            "cost_treatments": {"fee": "ADDITIVE", "spread": "DECOMPOSITION", "depth_slippage": "DECOMPOSITION",
                "endogenous_impact": "DECOMPOSITION", "timing": "DECOMPOSITION", "implementation_shortfall": "DIAGNOSTIC_NOT_DEDUCTED_AGAIN"},
            "applicability": {"maker_fills": "NOT_APPLICABLE_MARKET_IOC", "funding": "NOT_APPLICABLE_SPOT",
                "borrow_financing": "NOT_APPLICABLE_FULLY_FUNDED_LONG_ONLY", "liquidation": "NOT_APPLICABLE_NO_MARGIN",
                "cancel_latency": "IOC_REMAINDER_CANCELS_AT_VENUE; CONFIRMATION_DELAY_RECORDED"},
            "fidelity": {"required": policy.minimum_fidelity, "observed": sorted({x.fidelity.value for x in tape.books}),
                "source_evidence": tape.evidence_kind, "scale_evidence": "MODELLED_AT_SCALE",
                "fill_evidence": "MODEL_ESTIMATE_NOT_OBSERVED_FILL",
                "execution_confidence": "LIMITED_PUBLIC_SNAPSHOT_MODEL",
                "sampling_model": "SAMPLE_AND_HOLD_WITH_ADVERSE_DEPTH_AND_IMPACT_SCENARIOS",
                "maximum_observation_gap_ms": max(int((b.event_time - a.event_time).total_seconds() * 1000)
                    for a, b in zip(tape.books, tape.books[1:], strict=False)),
                "timestamp_semantics": "Modeled arrival clock; not a claim of observed intrainterval fill precision",
                "uncertainty_semantics": "Conditional scenario range, not an unconditional confidence interval",
                "queue_assumption": "NO_PASSIVE_FILLS", "hidden_liquidity": "NONE_ASSUMED",
                "limitations": list(tape.limitations) + ["Fixed G5 intent counterfactual; no strategy retuning",
                    "Public depth cannot empirically validate endogenous impact at untraded scale"]}}
