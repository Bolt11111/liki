"""Authenticated research-only HTTP control plane. No live-order routes exist."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from liki.core import Contract, DomainError, database_config, uid
from liki.governance_service import GovernanceService
from liki.operations import Operations
from liki.paper_service import PaperService, StopRequest, StopScope
from liki.store import Credential, Store
from liki.telegram import TelegramService, TelegramSettings

bearer = HTTPBearer(auto_error=False)


def credential(auth: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Credential:
    if auth is None or auth.scheme.lower() != "bearer":
        raise DomainError("UNAUTHENTICATED")
    return Credential(auth.credentials)


Auth = Annotated[Credential, Depends(credential)]


class EmergencyStop(Contract):
    reason: str = Field(min_length=1, max_length=500)


class OwnerAction(Contract):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


def create_app(store: Store | None = None, telegram_settings: TelegramSettings | None = None) -> FastAPI:
    store = store or Store(database_config()["app_dsn"])
    operations = Operations(store)
    paper = PaperService(store)
    governance = GovernanceService(store)
    telegram_settings = telegram_settings or TelegramSettings.from_environment()
    telegram = TelegramService(store, telegram_settings) if telegram_settings else None
    app = FastAPI(title="LIKI research control plane", version="0.1.0", docs_url=None, redoc_url=None)
    app.state.store = store

    @app.middleware("http")
    async def response_policy(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, error: DomainError):
        status = 401 if error.code == "UNAUTHENTICATED" else 403 if error.code in {
            "FORBIDDEN", "MANUAL_STOP_REQUIRES_OWNER", "OWNER_AUTH_REQUIRED"
        } else 404 if error.code.endswith("NOT_FOUND") else 409
        return JSONResponse({"error": error.code}, status_code=status,
                            headers={"WWW-Authenticate": "Bearer"} if status == 401 else {})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Pydantic's raw input may include credentials; return locations, never input values.
        return JSONResponse({"error": "INVALID_REQUEST", "fields": [
            {"location": list(e["loc"]), "type": e["type"]} for e in error.errors()]}, status_code=422)

    @app.exception_handler(psycopg.Error)
    async def database_error(request: Request, error: psycopg.Error):
        return JSONResponse({"error": "DATABASE_UNAVAILABLE", "correlation_id": uid("ERR")}, status_code=503)

    @app.get("/healthz")
    def health():
        return {"process": "UP", "real_money_execution": "PROHIBITED"}

    @app.get("/status")
    def status(auth: Auth):
        return operations.status(auth)

    @app.get("/requirements")
    def requirements(auth: Auth):
        return operations.coverage(auth)

    @app.get("/scheduler/queues")
    def queues(auth: Auth):
        return operations.queues(auth)

    @app.get("/scheduler/why-running")
    def activity(auth: Auth):
        return operations.activity(auth)

    @app.get("/scheduler/why-running/{run_id}")
    def run(run_id: str, auth: Auth):
        rows = operations.activity(auth, run_id=run_id)
        if not rows:
            raise DomainError("NOT_FOUND")
        return rows[0]

    @app.get("/agents/{agent_id}/why-running")
    def agent(agent_id: str, auth: Auth):
        return operations.activity(auth, agent_id=agent_id)

    @app.get("/campaigns")
    def campaigns(auth: Auth):
        return operations.query(auth, "SELECT * FROM campaigns ORDER BY created_at DESC LIMIT 100")

    @app.get("/campaigns/{campaign_id}")
    def campaign(campaign_id: str, auth: Auth):
        return operations.one(auth, "SELECT * FROM campaigns WHERE campaign_id=%s", (campaign_id,))

    @app.get("/hypotheses/{object_id}")
    def hypothesis(object_id: str, auth: Auth):
        return operations.research_object(auth, object_id, "hypothesis")

    @app.get("/branches/{object_id}")
    def branch(object_id: str, auth: Auth):
        return operations.research_object(auth, object_id, "branch")

    @app.get("/experiments/{object_id}")
    def experiment(object_id: str, auth: Auth):
        return operations.research_object(auth, object_id, "experiment")

    @app.get("/strategies/{object_id}/lineage")
    def lineage(object_id: str, auth: Auth):
        return operations.lineage(auth, object_id)

    @app.get("/gates/outcomes")
    def gate_outcomes(auth: Auth):
        return operations.gate_outcomes(auth)

    @app.get("/gates/{strategy_version_id}")
    def gates(strategy_version_id: str, auth: Auth):
        return operations.query(auth, "SELECT gate_decision_id,gate_id,snapshot_id,gate_version,"
            "decision,reason_code,decision_reason,state_before,state_after,created_at,event_id "
            "FROM gate_decisions WHERE strategy_version_id=%s ORDER BY gate_state_version_after", (strategy_version_id,))

    @app.get("/trials/{family_id}")
    def trials(family_id: str, auth: Auth):
        return operations.query(auth, "SELECT trial_event_id,campaign_id,trial_family_id,strategy_version_id,"
            "trial_type,selection_reason,started_at,infrastructure_retry,contamination_tags "
            "FROM trial_events WHERE trial_family_id=%s ORDER BY started_at LIMIT 500", (family_id,))

    @app.get("/statistical-capital/{campaign_id}")
    def statistical_capital(campaign_id: str, auth: Auth):
        return operations.statistical_capital(auth, campaign_id)

    @app.get("/holdout/exposure/{campaign_id}")
    def exposure(campaign_id: str, auth: Auth):
        return operations.query(auth, "SELECT holdout_id,trial_family_id,count(*) AS query_count,"
            "min(budget_after) AS remaining_budget,bool_or(researcher_exposure) AS researcher_exposed "
            "FROM holdout_query_events WHERE campaign_id=%s GROUP BY holdout_id,trial_family_id", (campaign_id,))

    @app.get("/incidents")
    def incidents(auth: Auth):
        return operations.query(auth, "SELECT incident_id,severity,status,state_version,opened_at,updated_at "
                                "FROM incidents ORDER BY opened_at DESC LIMIT 100")

    @app.get("/incidents/{incident_id}")
    def incident(incident_id: str, auth: Auth):
        return operations.one(auth, "SELECT incident_id,severity,status,state_version,opened_at,updated_at "
                              "FROM incidents WHERE incident_id=%s", (incident_id,))

    @app.get("/governance/proposals")
    def proposals(auth: Auth):
        return operations.query(auth, "SELECT proposal_id,proposal_version,status,classification,"
            "created_at,updated_at FROM governance_proposals ORDER BY created_at DESC LIMIT 100")

    @app.get("/governance/proposals/{proposal_id}")
    def proposal(proposal_id: str, auth: Auth):
        return operations.one(auth, "SELECT proposal_id,proposal_version,status,classification,"
            "approval_snapshot_hash,owner_delivery,created_at,updated_at "
            "FROM governance_proposals WHERE proposal_id=%s", (proposal_id,))

    @app.get("/governance/change-sets/{change_set_id}")
    def change_set(change_set_id: str, auth: Auth):
        return operations.one(auth, "SELECT change_set_id,state_version,created_at,revalidated_at,promoted_at "
            "FROM governance_change_sets WHERE change_set_id=%s", (change_set_id,))

    def owner_decision(proposal_id: str, body: OwnerAction, auth: Credential, key: str, decision):
        with store.transaction(auth) as (conn, actor):
            actor.require("owner_decision")
            row = conn.execute("SELECT classification FROM governance_proposals WHERE proposal_id=%s",
                               (proposal_id,)).fetchone()
            if not row:
                raise DomainError("NOT_FOUND")
            if not row["classification"]:
                raise DomainError("PROPOSAL_NOT_CLASSIFIED")
            return governance.decide(conn, actor, proposal_id, decision, body.reason,
                                     body.expected_version, key, row["classification"]["policy_version"])

    @app.post("/governance/proposals/{proposal_id}/owner-veto")
    def veto(proposal_id: str, body: OwnerAction, auth: Auth,
             idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
        return owner_decision(proposal_id, body, auth, idempotency_key, "VETO")

    @app.post("/governance/proposals/{proposal_id}/owner-approve")
    def approve(proposal_id: str, body: OwnerAction, auth: Auth,
                idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
        return owner_decision(proposal_id, body, auth, idempotency_key, "APPROVE")

    @app.get("/paper/status")
    def paper_status(auth: Auth):
        return operations.paper_status(auth)

    @app.get("/paper/orders")
    def orders(auth: Auth):
        return operations.query(auth, "SELECT paper_order_id,paper_run_id,instrument_id,venue_id,side,"
            "order_type,price::text,quantity::text,filled_quantity::text,final_state,updated_at "
            "FROM paper_orders ORDER BY created_at DESC LIMIT 200")

    @app.get("/risk/reservations")
    def reservations(auth: Auth):
        return operations.query(auth, "SELECT * FROM risk_reservations ORDER BY created_at DESC LIMIT 200")

    @app.get("/risk/reservations/{reservation_id}")
    def reservation(reservation_id: str, auth: Auth):
        return operations.one(auth, "SELECT * FROM risk_reservations WHERE reservation_id=%s", (reservation_id,))

    @app.post("/paper/emergency-stop")
    def emergency_stop(body: EmergencyStop, auth: Auth,
                       idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
        stop_id = paper.emergency_stop(auth, StopRequest(scope=StopScope.GLOBAL,
            scope_id=None, reason_code=body.reason, automatic=False), idempotency_key)
        return {"stop_id": stop_id, "real_money_execution": "PROHIBITED"}

    @app.post("/venues/{venue}/emergency-stop")
    def venue_stop(venue: str, body: EmergencyStop, auth: Auth,
                   idempotency_key: Annotated[str, Header(min_length=1, max_length=200)]):
        stop_id = paper.emergency_stop(auth, StopRequest(scope=StopScope.VENUE,
            scope_id=venue, reason_code=body.reason, automatic=False), idempotency_key)
        return {"stop_id": stop_id, "real_money_execution": "PROHIBITED"}

    @app.post("/telegram/webhook")
    def telegram_webhook(update: dict, x_telegram_bot_api_secret_token: Annotated[str, Header()] = ""):
        if telegram is None:
            return JSONResponse({"error": "TELEGRAM_NOT_CONFIGURED"}, status_code=503)
        return telegram.receive(x_telegram_bot_api_secret_token, update)

    web = Path(__file__).parent / "web"
    if web.is_dir():
        app.mount("/assets", StaticFiles(directory=web), name="assets")

        @app.get("/", include_in_schema=False)
        def index():
            return FileResponse(web / "index.html")

    return app


def main() -> None:
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "3000")),
                access_log=False, server_header=False)


if __name__ == "__main__":
    main()
