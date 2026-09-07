"""Independent G6 regressions using explicitly synthetic, hand-derived executions."""

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from liki.economics_gate import _calibration
from liki.finance.contracts import UnknownContractError
from liki.finance.derivatives import DerivativePosition, ForcedEvent, MarginMode
from liki.finance.economics import _case
from liki.finance.economics_contracts import EconomicsPolicy, ExecutionTape
from liki.finance.types import ContractKind, InstrumentSpec, Side
from tests.test_economics_gate import economics_policy, economics_tape, evaluate, impact_samples


D = Decimal


def flat_inputs():
    tape, policy = economics_tape(), economics_policy()
    for book in tape["books"]:
        book.update(bids=[{"price": "99", "quantity": "10"}],
                    asks=[{"price": "101", "quantity": "10"}])
    for sample in tape["latency_samples"]:
        sample.update(signal_ms=0, decision_ms=0, network_ms=1,
                      acknowledgement_ms=1, cancel_ms=1, market_data_ms=0)
    return tape, policy


def order(at, *, order_id="order-1", side="BUY", quantity="1"):
    return {"intent": {"client_order_id": order_id, "strategy_id": "candidate",
        "venue": "binance", "instrument_id": "BTCUSDT", "side": side,
        "quantity": quantity, "order_type": "MARKET", "limit_price": None,
        "information_cutoff_time": at - timedelta(milliseconds=1),
        "signal_ready_time": at, "order_eligible_time": at, "submission_time": at,
        "reduce_only": False, "post_only": False, "time_in_force": "IOC"}}


def case(tape, policy, orders):
    return _case(orders, D("1000"), tape["books"][-1]["event_time"],
                 ExecutionTape.model_validate(tape), EconomicsPolicy.model_validate(policy),
                 D("1"), 0, False, D("0"))


def test_in_flight_ioc_cannot_be_retroactively_rejected_by_later_ack_timeout():
    tape, policy = flat_inputs()
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    tape["latency_samples"][0]["acknowledgement_ms"] = 1000
    orders = [order(at), order(at + timedelta(milliseconds=1), order_id="already-in-flight")]
    result = case(tape, policy, orders)
    # Both were sent before the first acknowledgement could possibly time out.
    assert result["filled_quantity"] == D("2")
    assert [fill["order_id"] for fill in result["fills"]] == ["order-1", "already-in-flight"]
    assert result["cash"] == D("797.798")
    assert result["net_pnl"] == D("-2.202")


def test_signal_latency_reordering_does_not_bypass_message_limit():
    tape, policy = flat_inputs()
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    tape["latency_samples"][0]["signal_ms"] = 100
    tape["rules"][0]["message_limit"] = 1
    result = case(tape, policy, [order(at, order_id="slow-signal"),
        order(at + timedelta(milliseconds=1), order_id="fast-signal")])
    assert [fill["order_id"] for fill in result["fills"]] == ["fast-signal"]
    assert result["orders"][1]["reason"] == "VENUE_MESSAGE_RATE_LIMIT"
    assert result["cash"] == D("898.899")


def test_delayed_client_book_does_not_supply_stale_venue_execution_price():
    tape, policy = flat_inputs()
    event = tape["books"][3]["event_time"]
    tape["books"][3].update(available_at=event + timedelta(seconds=30),
        bids=[{"price": "149", "quantity": "10"}], asks=[{"price": "151", "quantity": "10"}])
    result = case(tape, policy, [order(event + timedelta(milliseconds=100))])
    assert result["fills"][0]["price"] == D("151")
    assert result["fills"][0]["fee"] == D(".151")
    assert result["orders"][0]["book_event_time"] == event
    assert result["net_pnl"] == D("-51.151")


def test_terminal_valuation_does_not_hide_known_venue_loss_behind_feed_delay():
    tape, policy = flat_inputs()
    terminal = tape["books"][-1]["event_time"]
    tape["books"][-1].update(available_at=terminal + timedelta(seconds=30),
        bids=[{"price": "49", "quantity": "10"}], asks=[{"price": "51", "quantity": "10"}])
    result = case(tape, policy, [order(tape["books"][2]["event_time"] + timedelta(milliseconds=100))])
    assert result["terminal_mark"] == D("50")
    assert result["net_pnl"] == D("-51.101")


@pytest.mark.parametrize("same_observation", [True, False])
def test_standing_depth_is_shared_and_not_replenished_by_identical_snapshot(same_observation):
    tape, policy = flat_inputs()
    for book in tape["books"]:
        book["asks"][0]["quantity"] = "1"
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    later = at + timedelta(milliseconds=10) if same_observation else at + timedelta(minutes=1)
    result = case(tape, policy, [order(at), order(later, order_id="competing-order")])
    assert result["filled_quantity"] == 1
    assert result["orders"][1]["reason"] == "NO_NATIVE_EXECUTABLE_LIQUIDITY"
    assert result["cash"] == D("898.899")


def test_participation_budget_is_shared_even_when_depth_is_plentiful():
    tape, policy = flat_inputs()
    for book in tape["books"]:
        book["traded_quantity"] = "10"
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    result = case(tape, policy, [order(at), order(at + timedelta(milliseconds=10), order_id="second")])
    assert result["filled_quantity"] == 1
    assert result["orders"][1]["reason"] == "NO_NATIVE_EXECUTABLE_LIQUIDITY"


def test_raw_off_tick_book_is_conflicting_metadata_not_a_rounding_opportunity():
    tape, policy = flat_inputs()
    for book in tape["books"]:
        book["asks"][0]["price"] = "100.5"
    with pytest.raises(ValueError):
        evaluate(tape=tape, policy=policy)


@pytest.mark.parametrize("upper,expected", [("101", "FILLED"), ("100.99", "REJECTED")])
def test_native_price_band_uses_executable_price_at_exact_boundary(upper, expected):
    tape, policy = flat_inputs()
    tape["rules"][0]["specification"]["price_upper"] = upper
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    result = case(tape, policy, [order(at)])
    assert result["orders"][0]["state"] == expected
    if expected == "REJECTED":
        assert result["orders"][0]["reason"] == "EXECUTION_PRICE_BAND"
        assert result["cash"] == 1000 and result["position"] == 0


def test_partial_sweep_shortfall_is_not_deducted_twice():
    tape, policy = flat_inputs()
    for book in tape["books"]:
        book["asks"] = [{"price": "100", "quantity": "2"}, {"price": "110", "quantity": "1"}]
        book["bids"] = [{"price": "99", "quantity": "10"}]
    tape["books"][-1].update(bids=[{"price": "104", "quantity": "10"}],
                            asks=[{"price": "106", "quantity": "10"}])
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    result = case(tape, policy, [order(at, quantity="4")])
    assert result["filled_quantity"] == 3 and result["fill_ratio"] == D(".75")
    assert result["orders"][0]["state"] == "PARTIALLY_FILLED_CANCELLED"
    assert result["cash"] == D("689.690")
    assert result["net_pnl"] == D("4.690")
    assert result["costs"]["fee"] == D(".310")
    assert result["costs"]["implementation_shortfall"] == D("11.810")
    assert result["gross_decision_price_pnl"] == D("16.5")
    assert result["net_pnl"] == result["gross_decision_price_pnl"] - result["costs"]["implementation_shortfall"]


def test_fill_time_tier_and_signed_fee_change_use_half_open_boundary():
    tape, policy = flat_inputs()
    boundary = tape["books"][3]["event_time"]
    tape["fees"][0]["schedule"]["effective_to"] = boundary
    new_fee = deepcopy(tape["fees"][0])
    new_fee["schedule"].update(version="rebate-v2", account_tier="observed-vip", rate="-0.001",
                               effective_from=boundary, effective_to=None)
    tape["fees"].append(new_fee)
    tape["account_tiers"][0]["effective_to"] = boundary
    new_tier = deepcopy(tape["account_tiers"][0])
    new_tier.update(tier="observed-vip", effective_from=boundary, effective_to=None,
                    basis="OBSERVED_ACCOUNT", source="test-only observed account state")
    tape["account_tiers"].append(new_tier)
    result = case(tape, policy, [order(boundary - timedelta(milliseconds=2)),
        order(boundary - timedelta(milliseconds=1), order_id="at-fee-boundary")])
    assert [fill["fee"] for fill in result["fills"]] == [D(".101"), D("-.101")]
    assert [row["account_tier"] for row in result["orders"]] == ["base", "observed-vip"]
    assert result["cash"] == D("798") and result["costs"]["fee"] == 0


@pytest.mark.parametrize("quantity", ["0", "1e-40", "0.999"])
def test_extremely_small_depth_never_creates_a_native_fill(quantity):
    tape, policy = flat_inputs()
    for book in tape["books"]:
        book["asks"][0]["quantity"] = quantity
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    result = case(tape, policy, [order(at)])
    assert result["fills"] == [] and result["cash"] == 1000 and result["position"] == 0


def test_huge_order_cannot_turn_a_partial_fill_into_unlimited_capacity():
    tape, policy = flat_inputs()
    at = tape["books"][2]["event_time"] + timedelta(milliseconds=100)
    result = case(tape, policy, [order(at, quantity="1e40")])
    assert result["fills"] == [] and result["orders"][0]["reason"] == "POSITION_LIMIT"
    assert result["cash"] == 1000 and result["position"] == 0


@pytest.mark.parametrize("leak", ["duplicate_episode", "future_availability"])
def test_calibration_rejects_shared_episode_or_post_replay_knowledge(monkeypatch, leak):
    from liki.core import canonical

    tape, policy = flat_inputs()
    training, validation = impact_samples(), impact_samples(False)
    if leak == "duplicate_episode":
        validation["observations"][0]["episode_id"] = training["observations"][0]["episode_id"]
    else:
        validation["observations"][0]["available_at"] = tape["books"][0]["event_time"]
    payloads = {"training": canonical(training).encode(), "validation": canonical(validation).encode()}

    def raw(_store, _conn, _actor, digest, _artifacts, _cutoff):
        return payloads[digest], {}

    monkeypatch.setattr("liki.economics_gate._raw", raw)
    with pytest.raises(UnknownContractError, match="CALIBRATION_LEAKAGE"):
        _calibration(None, None, None, EconomicsPolicy.model_validate(policy),
                     ExecutionTape.model_validate(tape), {"created_at": tape["books"][-1]["event_time"]}, {})


def inverse_position(side=Side.BUY):
    source = economics_tape()["rules"][0]["specification"]
    spec = InstrumentSpec.model_validate({**source, "contract_kind": ContractKind.INVERSE_PERPETUAL,
        "quote_currency": "USD", "settlement_currency": "BTC", "multiplier": "1",
        "maintenance_margin_rate": "0.1"})
    return DerivativePosition(side, D("100"), D("100"), spec, MarginMode.ISOLATED, D("2"))


@pytest.mark.parametrize("side,rate,expected", [
    (Side.BUY, ".01", "-.005"), (Side.BUY, "-.01", ".005"),
    (Side.SELL, ".01", ".005"), (Side.SELL, "-.01", "-.005"),
])
def test_inverse_funding_uses_settlement_notional_and_correct_sign(side, rate, expected):
    # 100 contracts * USD 1 / (USD 200 per BTC) = BTC .5, not USD 20,000.
    assert inverse_position(side).funding_payment(D(rate), D("200")) == D(expected)


def test_inverse_maintenance_margin_is_in_collateral_currency():
    position = inverse_position()
    assert position.unrealized_pnl(D("200")) == D(".5")
    assert position.maintenance_margin(D("200")) == D(".05")


def test_inverse_positive_equity_is_not_liquidated_by_quote_unit_margin():
    assert inverse_position().liquidatable(D("200")) is False


def test_inverse_forced_fee_uses_settlement_notional():
    event = ForcedEvent("LIQUIDATION", D("200"), D(".01"), "MODEL_ESTIMATE")
    assert event.convert(inverse_position()) == (D(".5"), D(".005"))
