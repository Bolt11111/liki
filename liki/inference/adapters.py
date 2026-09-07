"""Native Anthropic Messages and OpenAI chat-compatible transports."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Awaitable, Callable
from ipaddress import ip_address
from typing import Any
from urllib.parse import urljoin

import httpx
from pydantic import ValidationError

from .types import ProviderRoute, RawProviderResponse, Usage


class ProviderTransportError(RuntimeError):
    def __init__(self, error_class: str, *, retryable: bool = True) -> None:
        super().__init__(error_class)
        self.error_class = error_class
        self.retryable = retryable


ApiKeyResolver = Callable[[ProviderRoute], Awaitable[str]]
HostResolver = Callable[[str, int], Awaitable[tuple[str, ...]]]


def _endpoint(route: ProviderRoute, path: str) -> str:
    base = str(route.base_url).rstrip("/") + "/"
    endpoint = urljoin(base, path.lstrip("/"))
    parsed = httpx.URL(endpoint)
    if (
        parsed.host is None
        or parsed.host.casefold().rstrip(".")
        not in {host.casefold().rstrip(".") for host in route.allowed_hosts}
        or parsed.scheme != "https"
    ):
        raise ProviderTransportError("unsafe_provider_endpoint", retryable=False)
    return endpoint


async def _resolve_public_hosts(host: str, port: int) -> tuple[str, ...]:
    try:
        results = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as exc:
        raise ProviderTransportError("provider_dns_resolution_failed") from exc
    addresses = tuple(sorted({str(result[4][0]) for result in results}))
    if not addresses:
        raise ProviderTransportError("provider_dns_resolution_failed")
    if any(not ip_address(address).is_global for address in addresses):
        raise ProviderTransportError("unsafe_provider_dns_resolution", retryable=False)
    return addresses


class BaseAdapter:
    def __init__(
        self,
        client: httpx.AsyncClient,
        key_resolver: ApiKeyResolver,
        host_resolver: HostResolver = _resolve_public_hosts,
    ) -> None:
        self._client = client
        self._key_resolver = key_resolver
        self._host_resolver = host_resolver

    async def _verified_endpoint(self, route: ProviderRoute, path: str) -> str:
        endpoint = _endpoint(route, path)
        parsed = httpx.URL(endpoint)
        assert parsed.host is not None  # `_endpoint` rejects a missing host.
        addresses = await self._host_resolver(parsed.host, parsed.port or 443)
        if not addresses or any(not ip_address(address).is_global for address in addresses):
            raise ProviderTransportError("unsafe_provider_dns_resolution", retryable=False)
        return endpoint

    async def _post(self, route: ProviderRoute, path: str, headers: dict[str, str], payload: dict[str, Any]) -> Any:
        try:
            response = await self._client.post(
                await self._verified_endpoint(route, path),
                headers=headers,
                json=payload,
                timeout=route.capabilities.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTransportError("timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderTransportError("transport") from exc
        if response.status_code < 200 or response.status_code >= 300:
            retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
            raise ProviderTransportError(f"http_{response.status_code}", retryable=retryable)
        try:
            return response.json(), response.status_code, response.headers
        except json.JSONDecodeError as exc:
            raise ProviderTransportError("malformed_provider_json") from exc


class AnthropicMessagesAdapter(BaseAdapter):
    """Anthropic's native /v1/messages wire format; not OpenAI emulation."""

    async def invoke(self, route: ProviderRoute, system: str, prompt: str, effort: str) -> RawProviderResponse:
        await self._verified_endpoint(route, "/v1/messages")
        key = await self._key_resolver(route)
        payload: dict[str, Any] = {
            "model": route.model,
            "max_tokens": route.capabilities.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if effort and effort != "standard":
            # Anthropic requires a thinking budget strictly below max_tokens.
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": max(1, route.capabilities.max_output_tokens // 2),
            }
        body, status, headers = await self._post(
            route,
            "/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            payload,
        )
        if not isinstance(body, dict):
            raise ProviderTransportError("malformed_messages_response", retryable=False)
        blocks = body.get("content")
        if not isinstance(blocks, list):
            raise ProviderTransportError("malformed_messages_response", retryable=False)
        if any(not isinstance(block, dict) for block in blocks):
            raise ProviderTransportError("malformed_messages_response", retryable=False)
        usage = body.get("usage", {})
        if not isinstance(usage, dict):
            raise ProviderTransportError("malformed_messages_response", retryable=False)
        text = "".join(str(block.get("text", "")) for block in blocks if block.get("type") == "text")
        try:
            return RawProviderResponse(
                provider_request_id=headers.get("request-id"),
                text=text,
                usage=Usage(
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    cache_read_tokens=usage.get("cache_read_input_tokens"),
                    cache_write_tokens=usage.get("cache_creation_input_tokens"),
                ),
                model_version=body.get("model"),
                stop_reason=body.get("stop_reason"),
                http_status=status,
            )
        except ValidationError as exc:
            raise ProviderTransportError("malformed_messages_response", retryable=False) from exc


class OpenAIChatAdapter(BaseAdapter):
    async def invoke(self, route: ProviderRoute, system: str, prompt: str, effort: str) -> RawProviderResponse:
        await self._verified_endpoint(route, "/v1/chat/completions")
        key = await self._key_resolver(route)
        payload: dict[str, Any] = {
            "model": route.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": route.capabilities.max_output_tokens,
        }
        if effort and effort != "standard":
            payload["reasoning_effort"] = effort
        body, status, headers = await self._post(
            route,
            "/v1/chat/completions",
            {"authorization": f"Bearer {key}", "content-type": "application/json"},
            payload,
        )
        if not isinstance(body, dict):
            raise ProviderTransportError("malformed_chat_response", retryable=False)
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderTransportError("malformed_chat_response", retryable=False)
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            raise ProviderTransportError("malformed_chat_content", retryable=False)
        text = message.get("content")
        if not isinstance(text, str):
            raise ProviderTransportError("malformed_chat_content", retryable=False)
        usage = body.get("usage", {})
        if not isinstance(usage, dict):
            raise ProviderTransportError("malformed_chat_response", retryable=False)
        try:
            return RawProviderResponse(
                provider_request_id=headers.get("x-request-id") or body.get("id"),
                text=text,
                usage=Usage(
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    reasoning_tokens=usage.get("reasoning_tokens"),
                ),
                model_version=body.get("model"),
                stop_reason=choices[0].get("finish_reason"),
                http_status=status,
            )
        except ValidationError as exc:
            raise ProviderTransportError("malformed_chat_response", retryable=False) from exc
