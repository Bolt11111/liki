"""Strict loading of owner-supplied inference route configuration."""

from __future__ import annotations

import json
from pathlib import Path

from .types import ProviderRoute


def load_provider_routes(path: str | Path) -> tuple[ProviderRoute, ...]:
    """Load a route registry without resolving credentials or making network calls."""
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("routes"), list):
        raise ValueError("provider registry must contain a routes array")
    routes = tuple(ProviderRoute.model_validate(record) for record in document["routes"])
    if len({route.route_id for route in routes}) != len(routes):
        raise ValueError("provider registry route_id values must be unique")
    return routes
