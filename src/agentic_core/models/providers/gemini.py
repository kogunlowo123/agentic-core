"""Google Gemini generateContent adapter (Gemini API or Vertex AI)."""

from __future__ import annotations

from typing import Any

import httpx

from agentic_core.models.providers._http import HttpProvider
from agentic_core.models.types import ModelRequest, ModelResponse, ProviderProfile, Role


class GeminiProvider(HttpProvider):
    """Gemini adapter.

    For the Gemini API pass ``api_key``. For Vertex AI pass ``base_url`` of
    ``https://{region}-aiplatform.googleapis.com/v1/projects/{p}/locations/{region}/publishers/google``
    and an OAuth ``access_token`` obtained from workload identity.
    """

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        api_key: str | None = None,
        access_token: str | None = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if bool(api_key) == bool(access_token):
            raise ValueError(f"{profile.name}: provide exactly one of api_key or access_token")
        headers = {"content-type": "application/json"}
        if api_key:
            headers["x-goog-api-key"] = api_key
        else:
            headers["authorization"] = f"Bearer {access_token}"
        super().__init__(
            profile, base_url=base_url, headers=headers, timeout_s=timeout_s, transport=transport
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:
        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "model" if m.role is Role.ASSISTANT else "user",
                    "parts": [{"text": m.content}],
                }
                for m in request.conversation
            ],
            "generationConfig": {
                "maxOutputTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if request.system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": request.system_prompt}]}
        body, latency_ms = await self._post(
            f"/models/{self.profile.model}:generateContent", payload
        )

        candidates = body.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = body.get("promptFeedback")
            reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
            raise self._malformed(f"no candidates (blockReason={reason})")
        first = candidates[0]
        content = first.get("content") if isinstance(first, dict) else None
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        raw_usage = body.get("usageMetadata")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        return self._build_response(
            request,
            text=text,
            finish_reason=str(first.get("finishReason") or "unknown"),
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            latency_ms=latency_ms,
        )
