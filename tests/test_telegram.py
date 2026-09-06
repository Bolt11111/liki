import copy
import secrets

import httpx
import pytest

from liki.core import DomainError, utcnow
from liki.telegram import TelegramService, TelegramSettings, TelegramTransport


def settings(credentials):
    return TelegramSettings(101, 202, credentials["owner"], credentials["scheduler"],
                            "fixture-token-not-live", "fixture-secret-not-live")


def update():
    return {"update_id": secrets.randbits(60), "message": {"message_id": 1,
        "chat": {"id": 202, "type": "private"}, "from": {"id": 101, "is_bot": False},
        "date": int(utcnow().timestamp()), "text": "/status"}}


def test_telegram_auth_replay_private_chat_and_no_inference(store, credentials):
    config = settings(credentials)
    service = TelegramService(store, config)
    payload = update()
    with pytest.raises(DomainError, match="UNAUTHENTICATED"):
        service.receive("forged", payload)
    for bad in ("user", "group", "bot"):
        altered = copy.deepcopy(payload)
        if bad == "user":
            altered["message"]["from"]["id"] = 999
        elif bad == "group":
            altered["message"]["chat"]["type"] = "group"
        else:
            altered["message"]["from"]["is_bot"] = True
        with pytest.raises(DomainError, match="FORBIDDEN"):
            service.receive(config.webhook_secret, altered)
    result = service.receive(config.webhook_secret, payload)
    assert service.receive(config.webhook_secret, payload) == result
    assert result["status"] == "QUEUED"
    altered = copy.deepcopy(payload)
    altered["message"]["text"] = "/queues"
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        service.receive(config.webhook_secret, altered)
    with store.transaction(credentials["auditor"]) as (conn, _):
        record = conn.execute("SELECT message FROM notification_records WHERE notification_id=%s",
                              (result["notification_id"],)).fetchone()
        assert "PROHIBITED" in record["message"]
        assert conn.execute("SELECT count(*) AS n FROM notification_deliveries WHERE notification_id=%s",
                             (result["notification_id"],)).fetchone()["n"] == 0


def test_telegram_expired_commands_never_execute(store, credentials):
    config = settings(credentials)
    payload = update()
    payload["message"]["date"] -= 301
    with pytest.raises(DomainError, match="STALE_TELEGRAM_COMMAND"):
        TelegramService(store, config).receive(config.webhook_secret, payload)


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"ok": True, "result": {"message_id": 9, "chat": {"id": 202}}}, None),
    (200, {"ok": True, "result": {"message_id": 9, "chat": {"id": 999}}}, "UNKNOWN_DELIVERY"),
    (429, {"ok": False, "parameters": {"retry_after": 3}}, "TRANSIENT"),
    (403, {"ok": False}, "PERMANENT"),
    (502, {"ok": False}, "UNKNOWN_DELIVERY"),
])
def test_telegram_transport_requires_real_receipt(credentials, status, payload, expected):
    def handler(request):
        assert request.url.host == "api.telegram.org"
        assert b'"protect_content":true' in request.content
        return httpx.Response(status, json=payload)
    config = settings(credentials)
    transport = TelegramTransport(config, httpx.Client(transport=httpx.MockTransport(handler)))
    outcome = transport.send("Test-only message")
    assert outcome.failure == expected
    assert outcome.receipt == ("9" if expected is None else None)


def test_timeout_after_send_is_uncertain_not_success(credentials):
    def handler(request):
        raise httpx.ReadTimeout("Test timeout", request=request)
    transport = TelegramTransport(settings(credentials), httpx.Client(transport=httpx.MockTransport(handler)))
    assert transport.send("fixture").failure == "UNKNOWN_DELIVERY"
