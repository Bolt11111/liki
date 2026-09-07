from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal, localcontext

import pytest
from hypothesis import given, strategies as st

from liki.finance.execution_reference import fee_reference, latency_reference, sweep_reference


D = Decimal
LEVELS = ((D("100.01"), D("1.29")), (D("100.26"), D("2")))


def sweep(
    *,
    levels: tuple[tuple[Decimal, Decimal], ...] = LEVELS,
    side: str = "BUY",
    **overrides: Decimal,
) -> list[dict[str, Decimal]]:
    values = {
        "requested": D("2.58"), "maximum_quantity": D("2.7"), "lot_size": D("0.1"),
        "tick_size": D("0.25"), "fee_increment": D("0.01"), "fee_rate": D("0.001"),
        "impact_bps": D("0"), "traded_quantity": D("100"),
    }
    assert overrides.keys() <= values.keys()
    values.update(overrides)
    return sweep_reference(
        levels=levels, requested=values["requested"], maximum_quantity=values["maximum_quantity"],
        lot_size=values["lot_size"], tick_size=values["tick_size"], fee_increment=values["fee_increment"],
        fee_rate=values["fee_rate"], impact_bps=values["impact_bps"],
        traded_quantity=values["traded_quantity"], side=side,
    )


def test_hand_calculated_buy_golden():
    assert sweep() == [
        {"quantity": D("1.2"), "raw_price": D("100.01"), "price": D("100.25"), "fee": D("0.13")},
        {"quantity": D("1.3"), "raw_price": D("100.26"), "price": D("100.50"), "fee": D("0.14")},
    ]


def test_hand_calculated_sell_golden():
    assert sweep(side="SELL", levels=((D("100.26"), D("1.29")), (D("100.01"), D("2")))) == [
        {"quantity": D("1.2"), "raw_price": D("100.26"), "price": D("100.25"), "fee": D("0.13")},
        {"quantity": D("1.3"), "raw_price": D("100.01"), "price": D("100"), "fee": D("0.13")},
    ]


@pytest.mark.parametrize("rate,expected", [
    ("-0.001", [D("-0.12"), D("-0.13")]),
    ("-0.000001", [D("0"), D("0")]),
    ("0", [D("0"), D("0")]),
])
def test_signed_maker_rebates_round_toward_positive_infinity(rate, expected):
    assert [fill["fee"] for fill in sweep(fee_rate=D(rate))] == expected


@pytest.mark.parametrize("rate,expected", [("0.001", D("0.15")), ("-0.001", D("-0.10"))])
def test_non_power_of_ten_fee_increment_is_applied_to_each_fill(rate, expected):
    assert [fill["fee"] for fill in sweep(fee_rate=D(rate), fee_increment=D("0.05"))] == [expected, expected]


def test_two_level_nonlinear_impact_uses_entire_swept_quantity():
    # sqrt(4 / 16) * 100 bps = 50 bps for both levels, not one impact per fill.
    assert sweep(levels=((D("100"), D("1")), (D("200"), D("3"))),
                 requested=D("4"), maximum_quantity=D("10"), lot_size=D("1"),
                 tick_size=D("0.01"), impact_bps=D("100"), traded_quantity=D("16")) == [
        {"quantity": D("1"), "raw_price": D("100"), "price": D("100.50"), "fee": D("0.11")},
        {"quantity": D("3"), "raw_price": D("200"), "price": D("201"), "fee": D("0.61")},
    ]


def test_impact_excludes_depth_dust_that_cannot_form_individual_lots():
    fills = sweep(levels=((D("100"), D("0.19")), (D("200"), D("0.29"))),
                  requested=D("0.4"), tick_size=D("0.01"),
                  impact_bps=D("100"), traded_quantity=D("1.2"))
    assert fills == [
        {"quantity": D("0.1"), "raw_price": D("100"), "price": D("100.50"), "fee": D("0.02")},
        {"quantity": D("0.2"), "raw_price": D("200"), "price": D("201"), "fee": D("0.05")},
    ]


@pytest.mark.parametrize("side,levels,prices", [
    ("BUY", ((D("100"), D("1")), (D("110"), D("1"))), [D("100.82"), D("110.90")]),
    ("SELL", ((D("110"), D("1")), (D("100"), D("1"))), [D("109.10"), D("99.18")]),
])
def test_irrational_impact_adverse_rounding(side, levels, prices):
    fills = sweep(side=side, levels=levels, requested=D("2"), tick_size=D("0.01"),
                  impact_bps=D("100"), traded_quantity=D("3"))
    assert [fill["price"] for fill in fills] == prices


@pytest.mark.parametrize("levels", [(), ((D("100"), D("0")),),
                                     ((D("100"), D("1e-40")),),
                                     ((D("100"), D("0.09")), (D("101"), D("0.09")))])
def test_zero_or_sublot_displayed_liquidity_has_no_fills(levels):
    assert sweep(levels=levels) == []


@pytest.mark.parametrize("field", ["requested", "maximum_quantity", "traded_quantity"])
def test_zero_request_allowance_or_trading_volume_has_no_fills(field):
    assert sweep(levels=LEVELS, side="BUY", **{field: D("0")}) == []


def test_tiny_but_executable_liquidity_is_not_rounded_to_zero_arbitrarily():
    assert sweep(levels=((D("100"), D("2e-40")),), requested=D("2e-40"),
                 maximum_quantity=D("3e-40"), lot_size=D("1e-40"),
                 tick_size=D("0.01"), fee_increment=D("1e-43"),
                 impact_bps=D("100"), traded_quantity=D("8e-40")) == [
        {"quantity": D("2e-40"), "raw_price": D("100"), "price": D("100.50"), "fee": D("2.01e-41")},
    ]


def test_huge_quantity_and_fine_lot_size_preserve_native_amount():
    assert sweep(levels=((D("100.25"), D("2e30")),), requested=D("1e30"),
                 maximum_quantity=D("3e30"), lot_size=D("1e-8"),
                 traded_quantity=D("4e30")) == [
        {"quantity": D("1e30"), "raw_price": D("100.25"), "price": D("100.25"), "fee": D("1.0025e29")},
    ]


@pytest.mark.parametrize("impact", ["10000", "10001", "1000000"])
def test_sell_impact_must_not_produce_zero_or_negative_execution_price(impact):
    with pytest.raises(ValueError, match="nonpositive price"):
        sweep(side="SELL", levels=((D("100"), D("1")),), requested=D("1"),
              impact_bps=D(impact), traded_quantity=D("1"))


def test_positive_sell_price_below_a_tick_is_rejected_after_rounding():
    with pytest.raises(ValueError, match="tick rounding.*nonpositive price"):
        sweep(side="SELL", levels=((D("0.01"), D("1")),))


@pytest.mark.parametrize("side", ["buy", "sell", "", "HOLD"])
def test_invalid_sides_fail_closed(side):
    with pytest.raises(ValueError, match="side"):
        sweep(side=side)


@pytest.mark.parametrize("field", ["requested", "maximum_quantity", "lot_size", "tick_size",
                                   "fee_increment", "fee_rate", "impact_bps", "traded_quantity"])
@pytest.mark.parametrize("invalid", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_nonfinite_scalars_are_rejected_even_without_depth(field, invalid):
    with pytest.raises(ValueError, match="finite"):
        sweep(levels=(), side="BUY", **{field: D(invalid)})


@pytest.mark.parametrize("invalid", ["NaN", "sNaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("price_invalid", [False, True])
def test_nonfinite_levels_are_rejected_even_without_allowance(invalid, price_invalid):
    level = (D(invalid), D("1")) if price_invalid else (D("100"), D(invalid))
    with pytest.raises(ValueError, match="finite"):
        sweep(levels=(level,), maximum_quantity=D("0"))


@pytest.mark.parametrize("field", ["requested", "maximum_quantity", "impact_bps", "traded_quantity"])
def test_negative_quantities_and_impact_are_rejected(field):
    with pytest.raises(ValueError, match="nonnegative"):
        sweep(levels=LEVELS, side="BUY", **{field: D("-0.0001")})


@pytest.mark.parametrize("field", ["lot_size", "tick_size", "fee_increment"])
@pytest.mark.parametrize("invalid", ["0", "-0.0001"])
def test_native_increments_must_be_positive(field, invalid):
    with pytest.raises(ValueError, match="positive"):
        sweep(levels=LEVELS, side="BUY", **{field: D(invalid)})


@pytest.mark.parametrize("level", [(D("0"), D("1")), (D("-1"), D("1")),
                                   (D("100"), D("-0.0001"))])
def test_invalid_level_prices_and_quantities_fail_closed(level):
    with pytest.raises(ValueError, match="positive"):
        sweep(levels=(level,))


def test_explicit_precision_is_independent_of_callers_decimal_context():
    expected = sweep(impact_bps=D("81.123456789"))
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        assert sweep(impact_bps=D("81.123456789")) == expected
        assert context.prec == 4 and context.rounding == ROUND_DOWN


def test_native_rounding_preserves_just_below_lot_and_tick_boundaries():
    assert sweep(levels=((D("100.00000000000000000000000000000000000000000000001"), D("1")),),
                 requested=D("0.99999999999999999999999999999999999999999999999999"),
                 lot_size=D("0.1"), tick_size=D("0.01"), fee_rate=D("0")) == [
        {"quantity": D("0.9"),
         "raw_price": D("100.00000000000000000000000000000000000000000000001"),
         "price": D("100.01"), "fee": D("0")},
    ]


@given(depth=st.lists(st.integers(0, 10000), min_size=0, max_size=12),
       requested=st.integers(0, 100000), allowance=st.integers(0, 100000))
def test_sweep_conserves_amount_and_never_borrows_depth_dust(depth, requested, allowance):
    levels = tuple((D(100 + index), D(quantity) / 100) for index, quantity in enumerate(depth))
    fills = sweep(levels=levels, requested=D(requested) / 100,
                  maximum_quantity=D(allowance) / 100)
    actual = sum((fill["quantity"] for fill in fills), D(0))
    expected_lots = min(requested // 10, allowance // 10, sum(quantity // 10 for quantity in depth))
    assert actual == D(expected_lots) / 10
    remaining_lots = expected_lots
    expected_allocations = []
    for index, quantity in enumerate(depth):
        lots = min(quantity // 10, remaining_lots)
        if lots:
            expected_allocations.append((D(100 + index), D(lots) / 10))
            remaining_lots -= lots
    assert [(fill["raw_price"], fill["quantity"]) for fill in fills] == expected_allocations
    assert all(set(fill) == {"quantity", "raw_price", "price", "fee"} for fill in fills)
    assert all(isinstance(value, Decimal) for fill in fills for value in fill.values())


REFERENCE_TIME = datetime(2025, 1, 1, tzinfo=UTC)


def fee_row(*, available_at=REFERENCE_TIME, **changes):
    schedule = {
        "version": "fee-v1", "venue": "x", "instrument_id": "BTC-USD",
        "account_tier": "base", "liquidity_role": "TAKER", "rate": D("0.001"),
        "effective_from": REFERENCE_TIME - timedelta(days=1), "effective_to": None,
        "source": "historical fee schedule",
    }
    schedule.update(changes)
    return {"schedule": schedule, "available_at": available_at}


def tier_row(**changes):
    row = {
        "tier": "base", "effective_from": REFERENCE_TIME - timedelta(days=1),
        "effective_to": None, "available_at": REFERENCE_TIME,
        "basis": "OBSERVED_ACCOUNT", "source": "historical account state",
    }
    row.update(changes)
    return row


def selected_fee(*, fees=None, tiers=None, when=REFERENCE_TIME):
    return fee_reference(fees=[fee_row()] if fees is None else fees,
                         tiers=[tier_row()] if tiers is None else tiers,
                         venue="x", instrument_id="BTC-USD", when=when)


@pytest.mark.parametrize("rate", ["0.001", "0", "-0.0002"])
def test_fee_selection_preserves_positive_zero_and_signed_rebate_rates(rate):
    assert selected_fee(fees=[fee_row(rate=D(rate))]) == {
        "fee_version": "fee-v1", "rate": D(rate), "account_tier": "base",
    }


@pytest.mark.parametrize("field,value", [
    ("venue", "other"), ("instrument_id", "ETH-USD"),
    ("account_tier", "vip"), ("liquidity_role", "MAKER"),
])
def test_fee_selection_ignores_unrelated_identity_tier_and_passive_fees(field, value):
    unrelated = fee_row(**{field: value})
    assert selected_fee(fees=[unrelated, fee_row()])["fee_version"] == "fee-v1"
    with pytest.raises(ValueError, match="unknown.*taker fee"):
        selected_fee(fees=[unrelated])


@pytest.mark.parametrize("microseconds,version,tier", [(-1, "old", "base"), (0, "new", "vip"), (1, "new", "vip")])
def test_fee_and_account_tier_effective_intervals_are_half_open(microseconds, version, tier):
    known = REFERENCE_TIME - timedelta(days=2)
    fees = [
        fee_row(version="old", effective_to=REFERENCE_TIME, available_at=known),
        fee_row(version="new", account_tier="vip", effective_from=REFERENCE_TIME, available_at=known),
    ]
    tiers = [tier_row(effective_to=REFERENCE_TIME, available_at=known),
             tier_row(tier="vip", effective_from=REFERENCE_TIME, available_at=known)]
    assert selected_fee(fees=fees, tiers=tiers, when=REFERENCE_TIME + timedelta(microseconds=microseconds)) == {
        "fee_version": version, "rate": D("0.001"), "account_tier": tier,
    }


@pytest.mark.parametrize("row_kind", ["fee", "tier"])
@pytest.mark.parametrize("boundary", ["not_started", "expired"])
def test_fee_or_tier_missing_at_effective_boundaries_fails_closed(row_kind, boundary):
    changes = ({"effective_from": REFERENCE_TIME + timedelta(microseconds=1)}
               if boundary == "not_started" else {"effective_to": REFERENCE_TIME})
    with pytest.raises(ValueError, match="unknown or conflicting"):
        if row_kind == "fee":
            selected_fee(fees=[fee_row(**changes)])
        else:
            selected_fee(tiers=[tier_row(**changes)])


@pytest.mark.parametrize("row_kind", ["fee", "tier"])
@pytest.mark.parametrize("microseconds", [-1, 0, 1])
def test_fee_and_tier_availability_is_causal_and_inclusive(row_kind, microseconds):
    available_at = REFERENCE_TIME + timedelta(microseconds=microseconds)
    fees = [fee_row(available_at=available_at)] if row_kind == "fee" else [fee_row()]
    tiers = [tier_row(available_at=available_at)] if row_kind == "tier" else [tier_row()]
    if microseconds > 0:
        with pytest.raises(ValueError, match="not yet available"):
            selected_fee(fees=fees, tiers=tiers)
    else:
        assert selected_fee(fees=fees, tiers=tiers)["rate"] == D("0.001")


@pytest.mark.parametrize("row_kind", ["fee", "tier"])
@pytest.mark.parametrize("late_duplicate", [False, True])
def test_duplicate_effective_fee_or_tier_cannot_be_hidden_by_availability(row_kind, late_duplicate):
    available_at = REFERENCE_TIME + timedelta(seconds=1) if late_duplicate else REFERENCE_TIME
    with pytest.raises(ValueError, match="conflicting"):
        if row_kind == "fee":
            selected_fee(fees=[fee_row(), fee_row(available_at=available_at)])
        else:
            selected_fee(tiers=[tier_row(), tier_row(available_at=available_at)])


@pytest.mark.parametrize("row_kind", ["fee", "tier"])
def test_missing_fee_or_tier_never_defaults_to_zero_or_base(row_kind):
    with pytest.raises(ValueError, match="unknown"):
        if row_kind == "fee":
            selected_fee(fees=[])
        else:
            selected_fee(tiers=[])


@pytest.mark.parametrize("rate", ["NaN", "sNaN", "Infinity", "-Infinity"])
def test_reference_fee_rate_rejects_nonfinite_cost(rate):
    with pytest.raises(ValueError, match="finite"):
        selected_fee(fees=[fee_row(rate=D(rate))])


def latency_sample(**changes):
    sample = {"market_data_ms": 10, "signal_ms": 20, "decision_ms": 30, "network_ms": 40,
              "acknowledgement_ms": 500, "cancel_ms": 1000, "sample_id": "observed"}
    sample.update(changes)
    return sample


@pytest.mark.parametrize("submission_ms,sent_ms,arrival_ms", [(0, 60, 100), (60, 60, 100), (100, 100, 140)])
def test_latency_oracle_uses_maximum_submission_and_delayed_signal(submission_ms, sent_ms, arrival_ms):
    intent = {"signal_ready_time": REFERENCE_TIME,
              "submission_time": REFERENCE_TIME + timedelta(milliseconds=submission_ms)}
    assert latency_reference(intent, latency_sample()) == (
        REFERENCE_TIME + timedelta(milliseconds=sent_ms),
        REFERENCE_TIME + timedelta(milliseconds=arrival_ms),
    )


@pytest.mark.parametrize("component", ["market_data_ms", "signal_ms", "decision_ms", "network_ms"])
def test_each_latency_component_including_spikes_contributes_exactly_once(component):
    sample = latency_sample(market_data_ms=0, signal_ms=0, decision_ms=0, network_ms=0)
    sample[component] = 86400001
    intent = {"signal_ready_time": REFERENCE_TIME, "submission_time": REFERENCE_TIME}
    sent, arrival = latency_reference(intent, sample)
    delay = timedelta(days=1, milliseconds=1)
    assert sent == (REFERENCE_TIME if component == "network_ms" else REFERENCE_TIME + delay)
    assert arrival == REFERENCE_TIME + delay


def test_zero_latency_does_not_add_acknowledgement_or_cancel_to_arrival():
    intent = {"signal_ready_time": REFERENCE_TIME, "submission_time": REFERENCE_TIME}
    sample = latency_sample(market_data_ms=0, signal_ms=0, decision_ms=0, network_ms=0)
    assert latency_reference(intent, sample) == (REFERENCE_TIME, REFERENCE_TIME)


@pytest.mark.parametrize("component", ["market_data_ms", "signal_ms", "decision_ms", "network_ms"])
@pytest.mark.parametrize("invalid", [-1, 0.5, True])
def test_latency_requires_nonnegative_integer_millisecond_components(component, invalid):
    intent = {"signal_ready_time": REFERENCE_TIME, "submission_time": REFERENCE_TIME}
    with pytest.raises(ValueError, match="nonnegative integer"):
        latency_reference(intent, latency_sample(**{component: invalid}))
