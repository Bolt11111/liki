from fastapi.testclient import TestClient

from liki.core import uid
from liki.operations import Operations
from liki.server import create_app


def headers(credentials, role="auditor"):
    return {"Authorization": "Bearer " + credentials[role].token}


def test_http_requires_auth_and_never_exposes_live_order_routes(store, credentials):
    client = TestClient(create_app(store))
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer forged"}).status_code == 401
    status = client.get("/status", headers=headers(credentials))
    assert status.status_code == 200
    assert status.json()["real_money_execution"] == "PROHIBITED"
    assert status.json()["production_acceptance"] == "NOT_ACCEPTED"
    assert status.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in status.headers["content-security-policy"]
    for route in ("/live/orders", "/orders", "/execution/orders", "/mode/live"):
        assert client.post(route, json={}, headers=headers(credentials, "owner")).status_code == 404


def test_http_read_models_are_backed_by_database(store, credentials):
    client = TestClient(create_app(store))
    for path in ("/requirements", "/campaigns", "/incidents", "/governance/proposals",
                 "/scheduler/queues", "/scheduler/why-running", "/paper/status",
                 "/paper/orders", "/risk/reservations"):
        response = client.get(path, headers=headers(credentials))
        assert response.status_code == 200, (path, response.text)
    assert client.get("/campaigns/" + uid("ABSENT"), headers=headers(credentials)).status_code == 404
    requirements = client.get("/requirements", headers=headers(credentials)).json()
    assert requirements["total"] == sum(requirements["counts"].values())


def test_stop_forbidden_for_research_and_never_echoes_invalid_input(store, credentials):
    client = TestClient(create_app(store))
    response = client.post("/paper/emergency-stop", headers={**headers(credentials, "research"),
        "Idempotency-Key": uid("HTTP")}, json={"reason": "safety"})
    assert response.status_code == 403
    secret = "must-not-be-echoed-in-a-validation-error"
    response = client.post("/paper/emergency-stop", headers=headers(credentials, "owner"),
                           json={"credential": secret})
    assert response.status_code == 422
    assert secret not in response.text


def test_financial_read_models_keep_decimal_precision(store, credentials):
    result = Operations(store).query(credentials["auditor"],
        "SELECT 12345678901234567890.12345678901234567890::numeric AS amount")
    assert result[0]["amount"] == "12345678901234567890.12345678901234567890"


def test_telegram_webhook_disabled_without_explicit_configuration(store):
    response = TestClient(create_app(store)).post("/telegram/webhook", json={})
    assert response.status_code == 503
    assert response.json() == {"error": "TELEGRAM_NOT_CONFIGURED"}
