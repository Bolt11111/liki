from __future__ import annotations

import hashlib
import json
import os
import platform
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Mode(StrEnum):
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    READY_FOR_MICROLIVE = "READY_FOR_MICROLIVE"


class Classification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"
    SEALED = "SEALED"


class DomainError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def utcnow() -> datetime:
    return datetime.now(UTC)


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def canonical(value: Any) -> str:
    def encode(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            if not obj.is_finite():
                raise ValueError("Nonfinite Decimal is not evidence")
            return str(obj)
        if isinstance(obj, datetime):
            if obj.tzinfo is None:
                raise ValueError("Naive time is not permitted")
            return obj.astimezone(UTC).isoformat()
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="json")
        raise TypeError(f"Unsupported canonical type: {type(obj).__name__}")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=encode)


def content_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def environment_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    lock = root / "uv.lock"
    sources = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((root / "liki").rglob("*.py"))}
    return content_hash({"python": platform.python_version(), "architecture": platform.machine(),
                         "os": platform.system(), "timezone": "UTC", "sources": sources,
                         "lock": hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None})


def database_config() -> dict[str, str]:
    if os.environ.get("LIKI_DATABASE_URL"):
        return {"app_dsn": os.environ["LIKI_DATABASE_URL"],
                "owner_dsn": os.environ.get("LIKI_MIGRATION_DATABASE_URL", "")}
    path = Path(".runtime/database.json")
    if not path.exists():
        raise DomainError("DATABASE_NOT_CONFIGURED")
    return json.loads(path.read_text())
