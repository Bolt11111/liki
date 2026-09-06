"""Simple independent reconciliation path; do not import primary accounting arithmetic."""

from __future__ import annotations

from decimal import Decimal

from .accounting import Fill
from .types import ZERO


def independently_reconcile(starting_cash: Decimal, fills: list[Fill], mark: Decimal) -> dict[str, Decimal]:
    """FIFO lots written independently from LedgerState's moving-average control flow."""
    cash = Decimal(starting_cash)
    lots: list[tuple[Decimal, Decimal]] = []  # signed quantity, entry price
    realized = Decimal("0")
    total_fees = Decimal("0")
    total_other = Decimal("0")
    seen: set[str] = set()
    for fill in fills:
        if fill.fill_id in seen:
            raise ValueError("duplicate fill id")
        seen.add(fill.fill_id)
        incoming = fill.side.sign * fill.quantity
        cash -= incoming * fill.price + fill.fee
        total_fees += fill.fee
        for cost in fill.costs:
            if cost.treatment.value == "ADDITIVE":
                cash -= cost.amount
                total_other += cost.amount
        while incoming and lots and lots[0][0] * incoming < ZERO:
            quantity, entry = lots[0]
            closing = min(abs(quantity), abs(incoming))
            realized += closing * (fill.price - entry) * (Decimal("1") if quantity > ZERO else Decimal("-1"))
            remaining_lot = abs(quantity) - closing
            incoming_sign = Decimal("1") if incoming > ZERO else Decimal("-1")
            incoming = incoming_sign * (abs(incoming) - closing)
            if remaining_lot == ZERO:
                lots.pop(0)
            else:
                lots[0] = ((Decimal("1") if quantity > ZERO else Decimal("-1")) * remaining_lot, entry)
        if incoming:
            lots.append((incoming, fill.price))
    position = sum((q for q, _ in lots), ZERO)
    unrealized = sum((q * (Decimal(mark) - entry) for q, entry in lots), ZERO)
    return {"cash": cash, "position": position, "realized_pnl": realized, "unrealized_pnl": unrealized,
            "equity": cash + position * Decimal(mark), "fees": total_fees, "other_costs": total_other}
