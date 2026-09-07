from decimal import Decimal

import psycopg
from psycopg import sql
import pytest

from liki.core import DomainError, uid
from liki.finance import ContractKind, LiquidityRole
from liki.paper_service import PaperFill, PaperService
from tests.test_paper_service import active_service, now_contracts, order


@pytest.mark.parametrize("action", ["fill", "cancel"])
def test_hidden_reservation_fails_closed_and_rolls_back_all_financial_writes(store, credentials, database, action):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("ORDER")),
                              instrument, snapshot, envelope, "portfolio")
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("CREATE POLICY hidden_projection_test ON risk_reservations AS RESTRICTIVE "
                     "FOR SELECT TO liki_app USING (false)")
    with pytest.raises(DomainError, match="PAPER_RESERVATION_PROJECTION_MISSING"):
        if action == "fill":
            service.record_fill(credentials["paper"], order_id,
                PaperFill(uid("FILL"), now, Decimal("10"), Decimal("1"), Decimal("0.01"),
                          LiquidityRole.TAKER, "fill-v1"), "USD")
        else:
            service.cancel(credentials["paper"], order_id, uid("CANCEL"))
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        assert conn.execute("SELECT count(*) FROM paper_fills").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM paper_cash_ledger").fetchone()[0] == 0
        assert conn.execute("SELECT final_state,filled_quantity FROM paper_orders WHERE paper_order_id=%s",
                            (order_id,)).fetchone() == ("ACKNOWLEDGED", Decimal("0"))


@pytest.mark.parametrize("action", ["unknown", "cancel"])
def test_hidden_run_policy_cannot_commit_a_partial_order_transition(store, credentials, database, action):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("ORDER")),
                              instrument, snapshot, envelope, "portfolio")
    operation_key = uid("MISSING-RUN")
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("CREATE POLICY hidden_projection_test ON paper_runs AS RESTRICTIVE "
                     "FOR SELECT TO liki_app USING (false)")
    with pytest.raises(DomainError, match="PAPER_RUN_PROJECTION_MISSING"):
        if action == "unknown":
            service.mark_unknown(credentials["paper"], order_id, "RECONCILE", operation_key)
        else:
            service.cancel(credentials["paper"], order_id, operation_key)
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        assert conn.execute("SELECT final_state FROM paper_orders WHERE paper_order_id=%s",
                            (order_id,)).fetchone()[0] == "ACKNOWLEDGED"
        assert conn.execute("SELECT state FROM risk_reservations").fetchone()[0] == "HELD"
        assert not conn.execute("SELECT 1 FROM event_log WHERE operation_key=%s", (operation_key,)).fetchone()


@pytest.mark.parametrize("changes", [
    {"contract_kind": ContractKind.LINEAR_PERPETUAL}, {"multiplier": Decimal("2")}, {"settlement_currency": "BTC"},
])
def test_unsupported_contracts_cannot_enter_the_spot_paper_ledger(store, credentials, changes):
    _, instrument, _, run, _ = now_contracts()
    run = run.model_copy(update={"instruments": (instrument.model_copy(update=changes),)})
    with pytest.raises(DomainError, match="PAPER_CONTRACT_NOT_SUPPORTED"):
        PaperService(store).start_run(credentials["paper"], run, uid("START"))
    with store.transaction(credentials["auditor"]) as (conn, _):
        for table in ("paper_runs", "event_log", "artifacts"):
            assert conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table))).fetchone()["n"] == 0
