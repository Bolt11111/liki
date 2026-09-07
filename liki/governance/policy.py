"""Versioned protected-control policy used by deterministic classification."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .domain import ChangeClass, GovernanceError

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^(sha256:)?[0-9a-f]{64}$")]


class ProtectedControl(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    control_id: NonEmpty
    path_prefixes: tuple[NonEmpty, ...] = Field(min_length=1)
    minimum_class: ChangeClass


class GovernancePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    policy_id: NonEmpty
    policy_version: NonEmpty
    content_hash: Sha256
    protected_controls: tuple[ProtectedControl, ...] = Field(min_length=1)
    review_thresholds: dict[ChangeClass, int]

    @model_validator(mode="after")
    def _policy_is_complete(self) -> GovernancePolicy:
        expected = {ChangeClass.GREEN: 3, ChangeClass.AMBER: 5, ChangeClass.RED: 7}
        if self.review_thresholds != expected:
            raise ValueError("review thresholds are fixed at Green=3, Amber=5, Red=7")
        return self

    def floor_for(self, paths: tuple[str, ...], controls: tuple[str, ...]) -> tuple[ChangeClass, tuple[str, ...]]:
        floor = ChangeClass.GREEN
        matched: list[str] = []
        for control in self.protected_controls:
            path_match = any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for path in paths for prefix in control.path_prefixes)
            if control.control_id in controls or path_match:
                matched.append(control.control_id)
                if _rank(control.minimum_class) > _rank(floor):
                    floor = control.minimum_class
        return floor, tuple(matched)


def _rank(change_class: ChangeClass) -> int:
    return {ChangeClass.GREEN: 0, ChangeClass.AMBER: 1, ChangeClass.RED: 2}[change_class]


def load_governance_policy(path: Path | None = None) -> GovernancePolicy:
    """Load a content-addressed policy and reject tampering before it is used."""
    policy_path = path or Path(__file__).parents[2] / "config" / "governance_policy.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    supplied_hash = raw.pop("content_hash", None)
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    calculated = "sha256:" + sha256(canonical).hexdigest()
    if supplied_hash != calculated:
        raise GovernanceError("governance policy content hash mismatch")
    raw["content_hash"] = supplied_hash
    # JSON is the typed policy transport; strict domain records remain immutable.
    return GovernancePolicy.model_validate(raw, strict=False)
