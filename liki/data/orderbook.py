"""Sequence-validated L2 order book requiring snapshot/delta continuity."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import ensure_utc


class SequenceGapError(RuntimeError):
    pass


class OrderBookSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    last_update_id: int = Field(ge=0)
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    event_time: datetime
    received_at: datetime

    _utc = field_validator("event_time", "received_at")(ensure_utc)


class OrderBookDelta(BaseModel):
    model_config = ConfigDict(frozen=True)

    first_update_id: int = Field(ge=0)
    final_update_id: int = Field(ge=0)
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    event_time: datetime
    received_at: datetime

    _utc = field_validator("event_time", "received_at")(ensure_utc)

    @model_validator(mode="after")
    def ordered_ids(self) -> OrderBookDelta:
        if self.final_update_id < self.first_update_id:
            raise ValueError("final update ID must not precede first update ID")
        return self


class OrderBook:
    """State is invalidated on any missed sequence; caller must fetch a fresh snapshot."""

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.last_update_id: int | None = None
        self.valid = False
        self.gap_count = 0
        self.duplicate_count = 0

    @staticmethod
    def _apply(
        levels: dict[Decimal, Decimal], changes: tuple[tuple[Decimal, Decimal], ...]
    ) -> None:
        for price, quantity in changes:
            if price <= 0 or quantity < 0:
                raise ValueError("invalid order-book level")
            if quantity == 0:
                levels.pop(price, None)
            else:
                levels[price] = quantity

    def apply_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        self.bids, self.asks = {}, {}
        self._apply(self.bids, snapshot.bids)
        self._apply(self.asks, snapshot.asks)
        self.last_update_id = snapshot.last_update_id
        self.valid = True

    def apply_delta(self, delta: OrderBookDelta) -> None:
        if not self.valid or self.last_update_id is None:
            raise SequenceGapError("order book requires a snapshot before deltas")
        if delta.final_update_id <= self.last_update_id:
            self.duplicate_count += 1
            return
        if not (delta.first_update_id <= self.last_update_id + 1 <= delta.final_update_id):
            self.valid = False
            self.gap_count += 1
            raise SequenceGapError("order-book sequence gap; resynchronization required")
        self._apply(self.bids, delta.bids)
        self._apply(self.asks, delta.asks)
        self.last_update_id = delta.final_update_id

    def mid_price(self) -> Decimal:
        if not self.valid or not self.bids or not self.asks:
            raise SequenceGapError("order-book feature invalid without a continuous book")
        return (max(self.bids) + min(self.asks)) / Decimal(2)
