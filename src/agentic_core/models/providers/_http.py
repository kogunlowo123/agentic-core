"""Shared HTTP plumbing for REST-based providers."""

from __future__ import annotations

import time
from typing import Any

import httpx

from agentic_core.domain.errors import ProviderError
from agentic_core.models.types import ModelRequest, ModelResponse, ProviderProfile, TokenUsage

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


class HttpProvider:
    """Base class that owns an AsyncClient and maps transport failures."""

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._profile = profile
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            transport=transport,
        )

    @property
    def profile(self) -> ProviderProfile:
        return self._profile

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], float]:
        started = time.perf_counter()
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"{self._profile.name}: request timed out",
                provider=self._profile.name,
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                f"{self._profile.name}: transport error: {type(exc).__name__}",
                provider=self._profile.name,
                retryable=True,
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000
        if response.status_code >= 400:
            raise ProviderError(
                f"{self._profile.name}: HTTP {response.status_code}: {_error_detail(response)}",
                provider=self._profile.name,
                status_code=response.status_code,
                retryable=response.status_code in RETRYABLE_STATUS,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"{self._profile.name}: response is not JSON",
                provider=self._profile.name,
                status_code=response.status_code,
            ) from exc
        if not isinstance(body, dict):
            raise ProviderError(
                f"{self._profile.name}: response is not a JSON object",
                provider=self._profile.name,
                status_code=response.status_code,
            )
        return body, latency_ms

    def _build_response(
        self,
        request: ModelRequest,
        *,
        text: str,
        finish_reason: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        model: str | None = None,
    ) -> ModelResponse:
        return ModelResponse(
            request_id=request.request_id,
            provider=self._profile.name,
            model=model or self._profile.model,
            text=text,
            finish_reason=finish_reason,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            latency_ms=latency_ms,
            cost_usd=self._profile.estimate_cost(input_tokens, output_tokens),
        )

    def _malformed(self, detail: str) -> ProviderError:
        return ProviderError(
            f"{self._profile.name}: malformed response: {detail}", provider=self._profile.name
        )


def _error_detail(response: httpx.Response) -> str:
    """Extract a short error message without echoing the full body into logs."""
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase or "error"
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return str(error["message"])[:300]
        if isinstance(error, str):
            return error[:300]
    return response.reason_phrase or "error"
