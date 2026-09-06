"""Deterministic private-chat commands and receipt-verified Telegram delivery."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx

from liki.core import DomainError, canonical, content_hash, utcnow
from liki.operations import Operations
from liki.outbox import Notification, Outbox
from liki.store import Credential, Store


@dataclass(frozen=True)
class TelegramSettings:
    owner_user_id: int
    owner_chat_id: int
    owner_credential: Credential
    delivery_credential: Credential
    bot_token: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    max_command_age_seconds: int = 300

    @classmethod
    def from_environment(cls) -> TelegramSettings | None:
        if os.environ.get("LIKI_TELEGRAM_ENABLED") != "1":
            return None
        required = ("LIKI_TELEGRAM_USER_ID", "LIKI_TELEGRAM_CHAT_ID", "LIKI_TELEGRAM_BOT_TOKEN_FILE",
                    "LIKI_TELEGRAM_WEBHOOK_SECRET_FILE", "LIKI_TELEGRAM_OWNER_CREDENTIAL_FILE",
                    "LIKI_TELEGRAM_DELIVERY_CREDENTIAL_FILE")
        if not all(os.environ.get(key) for key in required):
            raise DomainError("TELEGRAM_CONFIGURATION_INCOMPLETE")
        def secret(key: str) -> str:
            path = Path(os.environ[key])
            if path.stat().st_mode & 0o077:
                raise DomainError("SECRET_FILE_PERMISSIONS_UNSAFE")
            value = path.read_text().strip()
            if not value:
                raise DomainError("TELEGRAM_CONFIGURATION_INCOMPLETE")
            return value
        return cls(int(os.environ[required[0]]), int(os.environ[required[1]]),
                   Credential(secret(required[4])), Credential(secret(required[5])),
                   secret(required[2]), secret(required[3]))


@dataclass(frozen=True)
class SendOutcome:
    receipt: str | None = None
    failure: Literal["TRANSIENT", "PERMANENT", "UNKNOWN_DELIVERY"] | None = None
    retry_after: int = 1


class TelegramTransport:
    def __init__(self, settings: TelegramSettings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)

    def send(self, message: str) -> SendOutcome:
        try:
            response = self.client.post("https://api.telegram.org/bot" + self.settings.bot_token + "/sendMessage",
                json={"chat_id": self.settings.owner_chat_id, "text": message,
                      "protect_content": True, "link_preview_options": {"is_disabled": True}})
        except (httpx.ConnectTimeout, httpx.ConnectError):
            return SendOutcome(failure="TRANSIENT")
        except httpx.HTTPError:
            return SendOutcome(failure="UNKNOWN_DELIVERY")
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            return SendOutcome(failure="UNKNOWN_DELIVERY")
        if not isinstance(payload, dict):
            return SendOutcome(failure="UNKNOWN_DELIVERY")
        if response.status_code == 429:
            parameters = payload.get("parameters", {})
            retry = parameters.get("retry_after") if isinstance(parameters, dict) else None
            return SendOutcome(failure="TRANSIENT", retry_after=retry if type(retry) is int and 1 <= retry <= 86400 else 60)
        if 400 <= response.status_code < 500:
            return SendOutcome(failure="PERMANENT")
        result = payload.get("result", {})
        if response.status_code != 200 or payload.get("ok") is not True or not isinstance(result, dict):
            return SendOutcome(failure="UNKNOWN_DELIVERY")
        chat = result.get("chat", {})
        if type(result.get("message_id")) is not int or not isinstance(chat, dict) or chat.get("id") != self.settings.owner_chat_id:
            return SendOutcome(failure="UNKNOWN_DELIVERY")
        return SendOutcome(receipt=str(result["message_id"]))


class TelegramService:
    def __init__(self, store: Store, settings: TelegramSettings, transport: TelegramTransport | None = None):
        self.store, self.settings = store, settings
        self.operations, self.outbox = Operations(store), Outbox(store)
        self.transport = transport or TelegramTransport(settings)

    def command(self, name: str, argument: str) -> dict | list:
        auth = self.settings.owner_credential
        if name == "/status":
            return self.operations.status(auth)
        if name in {"/active", "/why_running"}:
            return self.operations.activity(auth)
        if name == "/queues":
            return self.operations.queues(auth)
        if name == "/statistical_capital" and argument:
            return self.operations.statistical_capital(auth, argument)
        if name == "/trials" and argument:
            return self.operations.query(auth, "SELECT trial_family_id,count(*) AS attempts,"
                "count(*) FILTER(WHERE NOT infrastructure_retry) AS scientific_trials "
                "FROM trial_events WHERE trial_family_id=%s GROUP BY trial_family_id", (argument,))
        if name == "/governance":
            return self.operations.query(auth, "SELECT proposal_id,proposal_version,status,classification "
                "FROM governance_proposals ORDER BY created_at DESC LIMIT 20")
        if name == "/proposal" and argument:
            return self.operations.one(auth, "SELECT proposal_id,proposal_version,status,classification "
                "FROM governance_proposals WHERE proposal_id=%s", (argument,))
        if name == "/branch" and argument:
            row = self.operations.research_object(auth, argument, "branch")
            return {k: row[k] for k in ("object_id", "object_type", "campaign_id", "artifact_id", "content_hash")}
        if name == "/strategy" and argument:
            return self.operations.lineage(auth, argument)
        if name == "/agent" and argument:
            return self.operations.activity(auth, agent_id=argument)
        if name == "/frontier":
            return self.operations.query(auth, "SELECT strategy_version_id,gate_id,reason_code,created_at "
                "FROM gate_decisions WHERE decision='BORDERLINE' ORDER BY created_at DESC LIMIT 20")
        raise DomainError("COMMAND_NOT_AVAILABLE")

    def receive(self, secret: str, update: dict, *, now: datetime | None = None) -> dict:
        if not secret or not hmac.compare_digest(secret, self.settings.webhook_secret):
            raise DomainError("UNAUTHENTICATED")
        now = now or utcnow()
        message = update.get("message")
        if type(update.get("update_id")) is not int or not isinstance(message, dict):
            raise DomainError("INVALID_TELEGRAM_UPDATE")
        chat, sender = message.get("chat", {}), message.get("from", {})
        if not isinstance(chat, dict) or not isinstance(sender, dict) or chat.get("type") != "private" or (
            chat.get("id") != self.settings.owner_chat_id or sender.get("id") != self.settings.owner_user_id
            or sender.get("is_bot") is not False
        ):
            raise DomainError("FORBIDDEN")
        sent_at, text = message.get("date"), message.get("text")
        if type(sent_at) is not int or not -30 <= now.timestamp() - sent_at <= self.settings.max_command_age_seconds:
            raise DomainError("STALE_TELEGRAM_COMMAND")
        if not isinstance(text, str) or len(text) > 500:
            raise DomainError("INVALID_TELEGRAM_COMMAND")
        parts = text.strip().split(maxsplit=1)
        if not parts:
            raise DomainError("INVALID_TELEGRAM_COMMAND")
        name, argument = parts[0], parts[1] if len(parts) > 1 else ""
        digest = content_hash(update)
        with self.store.transaction(self.settings.owner_credential) as (conn, actor):
            actor.require("owner_decision")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            prior = conn.execute("SELECT * FROM telegram_inbox WHERE update_id=%s", (update["update_id"],)).fetchone()
            if prior:
                if prior["request_hash"] != digest or prior["principal_id"] != actor.principal_id:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return {"status": "QUEUED", "notification_id": prior["notification_id"]}
            try:
                result = self.command(name, argument)
                rendered = json.dumps(json.loads(canonical(result)), indent=2, ensure_ascii=False)
            except DomainError as error:
                rendered = error.code
            if len(rendered) > 3200:
                rendered = rendered[:3000] + "\n[Truncated; use the authenticated operator console for full state.]"
            notification = Notification(deduplication_key=f"telegram-update:{update['update_id']}",
                urgency="NORMAL", classification="INTERNAL", recipient_ref="owner", title="LIKI " + name[:100],
                message=rendered, object_id=str(update["update_id"]))
            nid = self.outbox.notify(conn, actor, notification)
            conn.execute("INSERT INTO telegram_inbox(update_id,request_hash,principal_id,command,notification_id) "
                         "VALUES(%s,%s,%s,%s,%s)", (update["update_id"], digest, actor.principal_id, name, nid))
            return {"status": "QUEUED", "notification_id": nid}

    def deliver_once(self) -> str | None:
        lease = self.outbox.claim(self.settings.delivery_credential, ("telegram.notification",))
        if lease is None:
            return None
        with self.store.transaction(self.settings.delivery_credential) as (conn, actor):
            actor.require("notification")
            row = conn.execute("SELECT * FROM notification_records WHERE notification_id=%s",
                               (lease.payload["notification_id"],)).fetchone()
            if not row or row["recipient_ref"] != "owner" or row["classification"] not in {"PUBLIC", "INTERNAL"}:
                return self.outbox.finish(self.settings.delivery_credential, lease, failure="PERMANENT")
        text = row["title"] + "\n" + row["message"]
        if row["required_action"]:
            text += "\nAction: " + row["required_action"]
        if row["deadline_at"]:
            text += "\nDeadline (UTC): " + row["deadline_at"].isoformat()
        result = self.transport.send(text)
        return self.outbox.finish(self.settings.delivery_credential, lease,
            receipt=result.receipt, failure=result.failure, retry_after=result.retry_after)
