"""Chat Completions adapter.

One adapter covers every endpoint that speaks the OpenAI Chat Completions
wire format:

* OpenAI (GPT models)                        auth=bearer
* Azure OpenAI                               auth=api-key, path includes deployment
* Azure AI Foundry model inference (Phi)     auth=bearer or api-key
* Self-hosted Llama via vLLM, TGI or Ollama  auth=bearer or none
"""

from __future__ import annotations

from typing import Any, Literal

import httpx

from agentic_core.models.providers._http import HttpProvider
from agentic_core.models.types import ModelRequest, ModelResponse, ProviderProfile

AuthStyle = Literal["bearer", "api-key", "none"]


class OpenAICompatibleProvider(HttpProvider):
    def __init__(
        self,
        profile: ProviderProfile,
        *,
        base_url: str,
        api_key: str | None = None,
        auth: AuthStyle = "bearer",
        path: str = "/v1/chat/completions",
        query: dict[str, str] | None = None,
        max_tokens_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens",
        send_model: bool = True,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        headers = {"content-type": "application/json"}
        if auth != "none":
            if not api_key:
                raise ValueError(f"{profile.name}: api_key required for auth={auth}")
            if auth == "bearer":
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["api-key"] = api_key
        super().__init__(
            profile, base_url=base_url, headers=headers, timeout_s=timeout_s, transport=transport
        )
        self._path = path if not query else f"{path}?{httpx.QueryParams(query)}"
        self._max_tokens_field = max_tokens_field
        self._send_model = send_model

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "messages": [{"role": m.role.value, "content": m.content} for m in request.messages],
            self._max_tokens_field: request.max_tokens,
            "temperature": request.temperature,
        }
        if self._send_model:
            payload["model"] = self.profile.model
        body, latency_ms = await self._post(self._path, payload)

        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise self._malformed("missing choices")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise self._malformed("missing message")
        raw_usage = body.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        return self._build_response(
            request,
            text=str(message.get("content") or ""),
            finish_reason=str(choices[0].get("finish_reason") or "unknown"),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=latency_ms,
            model=str(body.get("model") or self.profile.model),
        )
