"""Immutable raw-data storage and deterministic canonical hashing."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path
from typing import Any


def canonical_content_hash(records: Iterable[dict[str, Any]]) -> str:
    """Hash canonical records using a stable encoding independent of dict order."""
    encoded = "\n".join(
        json.dumps(record, sort_keys=True, separators=(",", ":"), default=str) for record in records
    ).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


class RawPayloadStore:
    """Content-addressed append-only store; an existing object may never be overwritten."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put(self, payload: bytes) -> str:
        digest = sha256(payload).hexdigest()
        target = self.root / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
        except FileExistsError as error:
            if target.read_bytes() != payload:
                raise RuntimeError("content-address collision or storage corruption") from error
        else:
            with os.fdopen(fd, "wb") as destination:
                destination.write(payload)
                destination.flush()
                os.fsync(destination.fileno())
        return f"sha256:{digest}"

    def get(self, content_hash: str) -> bytes:
        prefix, digest = content_hash.split(":", 1)
        if prefix != "sha256" or len(digest) != 64:
            raise ValueError("invalid content hash")
        content = (self.root / digest[:2] / digest).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise RuntimeError("raw payload integrity verification failed")
        return content
