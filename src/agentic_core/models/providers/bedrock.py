"""Amazon Bedrock Converse API adapter (Nova, Llama, Claude and others on Bedrock).

Credentials come from the standard AWS chain (IRSA / EKS Pod Identity in
Kubernetes), never from configuration files.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol, cast

from agentic_core.domain.errors import ProviderError
from agentic_core.models.types import (
    ModelRequest,
    ModelResponse,
    ProviderProfile,
    TokenUsage,
)

RETRYABLE_AWS_CODES = frozenset(
    {
        "ThrottlingException",
        "ServiceUnavailableException",
        "InternalServerException",
        "ModelNotReadyException",
        "ModelTimeoutException",
    }
)


class ConverseClient(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


class BedrockConverseProvider:
    def __init__(self, profile: ProviderProfile, *, client: ConverseClient) -> None:
        self._profile = profile
        self._client = client

    @classmethod
    def from_region(cls, profile: ProviderProfile, region: str) -> BedrockConverseProvider:
        import boto3  # noqa: PLC0415 - optional dependency: agentic-core[bedrock]

        client = boto3.client("bedrock-runtime", region_name=region)
        return cls(profile, client=cast(ConverseClient, client))

    @property
    def profile(self) -> ProviderProfile:
        return self._profile

    async def aclose(self) -> None:
        return None

    async def generate(self, request: ModelRequest) -> ModelResponse:
        kwargs: dict[str, Any] = {
            "modelId": self._profile.model,
            "messages": [
                {"role": m.role.value, "content": [{"text": m.content}]}
                for m in request.conversation
            ],
            "inferenceConfig": {
                "maxTokens": request.max_tokens,
                "temperature": request.temperature,
            },
        }
        if request.system_prompt:
            kwargs["system"] = [{"text": request.system_prompt}]

        started = time.perf_counter()
        try:
            body = await asyncio.to_thread(self._client.converse, **kwargs)
        except Exception as exc:
            raise _map_aws_error(self._profile.name, exc) from exc
        latency_ms = (time.perf_counter() - started) * 1000

        try:
            blocks = body["output"]["message"]["content"]
            usage = body["usage"]
        except (KeyError, TypeError) as exc:
            raise ProviderError(
                f"{self._profile.name}: malformed response", provider=self._profile.name
            ) from exc
        text = "".join(str(b.get("text", "")) for b in blocks if isinstance(b, dict))
        input_tokens = int(usage.get("inputTokens", 0))
        output_tokens = int(usage.get("outputTokens", 0))
        return ModelResponse(
            request_id=request.request_id,
            provider=self._profile.name,
            model=self._profile.model,
            text=text,
            finish_reason=str(body.get("stopReason") or "unknown"),
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            latency_ms=latency_ms,
            cost_usd=self._profile.estimate_cost(input_tokens, output_tokens),
        )


def _map_aws_error(provider: str, exc: Exception) -> ProviderError:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error", {})
        code = str(error.get("Code", "Unknown"))
        meta = response.get("ResponseMetadata", {})
        status = meta.get("HTTPStatusCode") if isinstance(meta, dict) else None
        return ProviderError(
            f"{provider}: {code}",
            provider=provider,
            status_code=int(status) if isinstance(status, int) else None,
            retryable=code in RETRYABLE_AWS_CODES,
        )
    return ProviderError(f"{provider}: {type(exc).__name__}", provider=provider, retryable=True)
