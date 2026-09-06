from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest

from liki.data import (
    CanonicalMarketRecord,
    DataQualityError,
    DatasetValidator,
    FeatureDefinition,
    FeatureResult,
    OrderBook,
    OrderBookDelta,
    OrderBookSnapshot,
    PriceKind,
    RawPayloadStore,
    SequenceGapError,
    asof_join,
    build_bars,
)


UTC = UTC
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def record(minutes: int, *, available_minutes: int | None = None) -> CanonicalMarketRecord:
    return CanonicalMarketRecord(
        instrument_id="binance:BTCUSDT",
        event_time=NOW + timedelta(minutes=minutes),
        available_at=NOW
        + timedelta(minutes=available_minutes if available_minutes is not None else minutes),
        price=Decimal("100") + minutes,
        quantity=Decimal("1"),
        price_kind=PriceKind.TRADE,
        raw_payload_hash="sha256:" + "a" * 64,
    )


def test_raw_store_is_content_addressed_and_integrity_checked(tmp_path):
    store = RawPayloadStore(tmp_path)
    hash_ = store.put(b'{"price":"100"}')
    assert store.put(b'{"price":"100"}') == hash_
    assert store.get(hash_) == b'{"price":"100"}'
    path = next(tmp_path.rglob("*"))
    if path.is_dir():
        path = next(path.iterdir())
    path.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="integrity"):
        store.get(hash_)


def test_validator_fails_closed_for_gap_and_lookahead():
    validator = DatasetValidator(max_gap=timedelta(minutes=2), max_staleness=timedelta(minutes=1))
    findings = validator.validate(
        [record(0), record(5), record(6, available_minutes=8)],
        decision_time=NOW + timedelta(minutes=6),
    )
    assert {finding.kind.value for finding in findings} >= {"gap", "lookahead"}
    with pytest.raises(DataQualityError):
        validator.require_usable(findings)


def test_bars_and_asof_join_preserve_availability_boundaries():
    bars = build_bars(
        [record(0), record(1), record(2, available_minutes=10)],
        interval=timedelta(minutes=5),
        as_of=NOW + timedelta(minutes=3),
    )
    assert len(bars) == 1 and bars[0].complete is False
    assert asof_join(
        [NOW + timedelta(minutes=3)],
        [(NOW + timedelta(minutes=4), "future")],
        max_staleness=timedelta(minutes=2),
    ) == (None,)
    definition = FeatureDefinition(
        feature_id="x",
        version="1",
        source_columns=("close",),
        lookback=timedelta(minutes=1),
        missing_value_policy="fail",
        normalization_policy="none",
        availability_semantics="source available",
        code_hash="sha256:" + "b" * 64,
    )
    with pytest.raises(ValueError, match="leakage"):
        FeatureResult(
            definition=definition,
            decision_time=NOW,
            value=1,
            latest_source_timestamp_used=NOW + timedelta(seconds=1),
        )


def test_order_book_requires_continuous_sequence():
    book = OrderBook()
    book.apply_snapshot(
        OrderBookSnapshot(
            last_update_id=10,
            bids=((Decimal("99"), Decimal("1")),),
            asks=((Decimal("101"), Decimal("1")),),
            event_time=NOW,
            received_at=NOW,
        )
    )
    book.apply_delta(
        OrderBookDelta(
            first_update_id=11,
            final_update_id=12,
            bids=((Decimal("100"), Decimal("1")),),
            asks=(),
            event_time=NOW,
            received_at=NOW,
        )
    )
    assert book.mid_price() == Decimal("100.5")
    with pytest.raises(SequenceGapError):
        book.apply_delta(
            OrderBookDelta(
                first_update_id=14,
                final_update_id=14,
                bids=(),
                asks=(),
                event_time=NOW,
                received_at=NOW,
            )
        )
    with pytest.raises(SequenceGapError):
        book.mid_price()
