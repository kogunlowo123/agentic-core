"""Anthropic Messages API adapter (Claude)."""

from __future__ import annotations

from typing import Any

import httpx

from agentic_core.models.providers._http import HttpProvider
from agentic_core.models.types import ModelRequest, ModelResponse, ProviderProfile

ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider(HttpProvider):
    def __init__(
        self,
        profile: ProviderProfile,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(
            profile,
            base_url=base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            timeout_s=timeout_s,
            transport=transport,
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.profile.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": m.role.value, "content": m.content} for m in request.conversation
            ],
        }
        if request.system_prompt:
            payload["system"] = request.system_prompt
        body, latency_ms = await self._post("/v1/messages", payload)

        blocks = body.get("content")
        usage = body.get("usage")
        if not isinstance(blocks, list) or not isinstance(usage, dict):
            raise self._malformed("missing content or usage")
        text = "".join(
            str(b.get("text", ""))
            for b in blocks
            if isinstance(b, dict) and b.get("type") == "text"
        )
        return self._build_response(
            request,
            text=text,
            finish_reason=str(body.get("stop_reason") or "unknown"),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            latency_ms=latency_ms,
            model=str(body.get("model") or self.profile.model),
        )
