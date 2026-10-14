from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agentic_core.domain.errors import ProviderError
from agentic_core.models.providers import (
    AnthropicProvider,
    BedrockConverseProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
)
from agentic_core.models.types import Message, ModelRequest, ProviderProfile, Role
from tests.conftest import Recorder

Profile = Callable[..., ProviderProfile]
RequestFactory = Callable[..., ModelRequest]


class TestAnthropic:
    async def test_maps_request_and_response(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        rec = Recorder(
            httpx.Response(
                200,
                json={
                    "model": "claude-x",
                    "content": [
                        {"type": "text", "text": "Hi "},
                        {"type": "tool_use", "id": "t"},
                        {"type": "text", "text": "there"},
                    ],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 1000, "output_tokens": 500},
                },
            )
        )
        provider = AnthropicProvider(profile("claude"), api_key="k", transport=rec.transport)
        resp = await provider.generate(request_factory("q", temperature=0.3))

        sent = rec.json()
        assert rec.requests[0].url.path == "/v1/messages"
        assert rec.requests[0].headers["x-api-key"] == "k"
        assert rec.requests[0].headers["anthropic-version"] == "2023-06-01"
        assert sent["system"] == "be brief"
        assert sent["messages"] == [{"role": "user", "content": "q"}]
        assert sent["temperature"] == 0.3
        assert resp.text == "Hi there"
        assert resp.model == "claude-x"
        assert resp.finish_reason == "end_turn"
        assert resp.cost_usd == pytest.approx((1000 * 1.0 + 500 * 2.0) / 1_000_000)
        await provider.aclose()

    async def test_omits_system_when_absent(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        rec = Recorder(httpx.Response(200, json={"content": [], "usage": {}}))
        provider = AnthropicProvider(profile(), api_key="k", transport=rec.transport)
        resp = await provider.generate(request_factory(system=None))
        assert "system" not in rec.json()
        assert resp.finish_reason == "unknown"

    async def test_malformed(self, profile: Profile, request_factory: RequestFactory) -> None:
        rec = Recorder(httpx.Response(200, json={"content": "nope"}))
        provider = AnthropicProvider(profile(), api_key="k", transport=rec.transport)
        with pytest.raises(ProviderError, match="malformed"):
            await provider.generate(request_factory())


class TestHttpErrors:
    @pytest.mark.parametrize(
        ("response", "retryable", "fragment"),
        [
            (httpx.Response(429, json={"error": {"message": "slow down"}}), True, "slow down"),
            (httpx.Response(503, json={"error": "overloaded"}), True, "overloaded"),
            (httpx.Response(400, json={"error": {"message": "bad"}}), False, "bad"),
            (httpx.Response(401, text="nope"), False, "Unauthorized"),
            (httpx.Response(404, json=["x"]), False, "Not Found"),
        ],
    )
    async def test_status_mapping(
        self,
        profile: Profile,
        request_factory: RequestFactory,
        response: httpx.Response,
        retryable: bool,
        fragment: str,
    ) -> None:
        provider = AnthropicProvider(profile(), api_key="k", transport=Recorder(response).transport)
        with pytest.raises(ProviderError, match=fragment) as info:
            await provider.generate(request_factory())
        assert info.value.retryable is retryable
        assert info.value.status_code == response.status_code

    @pytest.mark.parametrize(
        "exc",
        [httpx.ReadTimeout("t"), httpx.ConnectError("c")],
    )
    async def test_transport_failures_are_retryable(
        self, profile: Profile, request_factory: RequestFactory, exc: Exception
    ) -> None:
        provider = AnthropicProvider(profile(), api_key="k", transport=Recorder(exc).transport)
        with pytest.raises(ProviderError) as info:
            await provider.generate(request_factory())
        assert info.value.retryable

    @pytest.mark.parametrize(
        ("response", "fragment"),
        [
            (httpx.Response(200, text="<html>"), "not JSON"),
            (httpx.Response(200, json=[1, 2]), "not a JSON object"),
        ],
    )
    async def test_bad_bodies(
        self,
        profile: Profile,
        request_factory: RequestFactory,
        response: httpx.Response,
        fragment: str,
    ) -> None:
        provider = AnthropicProvider(profile(), api_key="k", transport=Recorder(response).transport)
        with pytest.raises(ProviderError, match=fragment):
            await provider.generate(request_factory())


class TestOpenAICompatible:
    async def test_bearer_openai(self, profile: Profile, request_factory: RequestFactory) -> None:
        rec = Recorder(
            httpx.Response(
                200,
                json={
                    "model": "gpt-x",
                    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                },
            )
        )
        provider = OpenAICompatibleProvider(
            profile("gpt"),
            base_url="https://api.openai.com",
            api_key="k",
            max_tokens_field="max_completion_tokens",
            transport=rec.transport,
        )
        resp = await provider.generate(request_factory("q"))
        sent = rec.json()
        assert rec.requests[0].headers["authorization"] == "Bearer k"
        assert sent["model"] == "gpt-model"
        assert sent["max_completion_tokens"] == 1024
        assert sent["messages"][0] == {"role": "system", "content": "be brief"}
        assert (resp.text, resp.usage.input_tokens, resp.model) == ("ok", 10, "gpt-x")

    async def test_azure_api_key_with_query(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        rec = Recorder(httpx.Response(200, json={"choices": [{"message": {"content": None}}]}))
        provider = OpenAICompatibleProvider(
            profile("azure-gpt"),
            base_url="https://r.openai.azure.com",
            api_key="k",
            auth="api-key",
            path="/openai/deployments/d/chat/completions",
            query={"api-version": "2024-10-21"},
            send_model=False,
            transport=rec.transport,
        )
        resp = await provider.generate(request_factory())
        req = rec.requests[0]
        assert req.headers["api-key"] == "k"
        assert req.url.params["api-version"] == "2024-10-21"
        assert "model" not in rec.json()
        assert resp.text == ""
        assert resp.usage.input_tokens == 0
        assert resp.finish_reason == "unknown"

    async def test_no_auth_self_hosted(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        rec = Recorder(httpx.Response(200, json={"choices": [{"message": {"content": "llama"}}]}))
        provider = OpenAICompatibleProvider(
            profile("llama"), base_url="http://vllm:8000", auth="none", transport=rec.transport
        )
        await provider.generate(request_factory())
        assert "authorization" not in rec.requests[0].headers

    def test_requires_key(self, profile: Profile) -> None:
        with pytest.raises(ValueError, match="api_key required"):
            OpenAICompatibleProvider(profile(), base_url="http://x")

    @pytest.mark.parametrize(
        "body", [{"choices": []}, {"choices": ["x"]}, {"choices": [{"message": "x"}]}]
    )
    async def test_malformed(
        self, profile: Profile, request_factory: RequestFactory, body: dict[str, Any]
    ) -> None:
        provider = OpenAICompatibleProvider(
            profile(),
            base_url="http://x",
            auth="none",
            transport=Recorder(httpx.Response(200, json=body)).transport,
        )
        with pytest.raises(ProviderError, match="malformed"):
            await provider.generate(request_factory())


class TestGemini:
    async def test_api_key(self, profile: Profile) -> None:
        rec = Recorder(
            httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {"parts": [{"text": "a"}, {"text": "b"}]},
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3},
                },
            )
        )
        provider = GeminiProvider(profile("gemini"), api_key="k", transport=rec.transport)
        request = ModelRequest(
            messages=(
                Message(role=Role.SYSTEM, content="sys"),
                Message(role=Role.USER, content="u1"),
                Message(role=Role.ASSISTANT, content="a1"),
                Message(role=Role.USER, content="u2"),
            )
        )
        resp = await provider.generate(request)
        sent = rec.json()
        assert rec.requests[0].url.path.endswith("/models/gemini-model:generateContent")
        assert rec.requests[0].headers["x-goog-api-key"] == "k"
        assert [c["role"] for c in sent["contents"]] == ["user", "model", "user"]
        assert sent["systemInstruction"] == {"parts": [{"text": "sys"}]}
        assert (resp.text, resp.finish_reason, resp.usage.output_tokens) == ("ab", "STOP", 3)

    async def test_access_token_vertex(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        rec = Recorder(httpx.Response(200, json={"candidates": [{"content": {}}]}))
        provider = GeminiProvider(
            profile(), access_token="t", base_url="https://vertex", transport=rec.transport
        )
        resp = await provider.generate(request_factory(system=None))
        assert rec.requests[0].headers["authorization"] == "Bearer t"
        assert "systemInstruction" not in rec.json()
        assert resp.text == ""

    async def test_blocked_prompt(self, profile: Profile, request_factory: RequestFactory) -> None:
        rec = Recorder(httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
        provider = GeminiProvider(profile(), api_key="k", transport=rec.transport)
        with pytest.raises(ProviderError, match="SAFETY"):
            await provider.generate(request_factory())

    @pytest.mark.parametrize("kwargs", [{}, {"api_key": "k", "access_token": "t"}])
    def test_exactly_one_credential(self, profile: Profile, kwargs: dict[str, str]) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            GeminiProvider(profile(), **kwargs)


class FakeBedrock:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class AwsError(Exception):
    def __init__(self, code: str, status: int | None = 400) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }


class TestBedrock:
    async def test_converse(self, profile: Profile, request_factory: RequestFactory) -> None:
        client = FakeBedrock(
            {
                "output": {"message": {"content": [{"text": "nova"}]}},
                "usage": {"inputTokens": 5, "outputTokens": 6},
                "stopReason": "end_turn",
            }
        )
        provider = BedrockConverseProvider(
            profile("nova", model="amazon.nova-pro-v1:0"), client=client
        )
        resp = await provider.generate(request_factory("q"))
        call = client.calls[0]
        assert call["modelId"] == "amazon.nova-pro-v1:0"
        assert call["system"] == [{"text": "be brief"}]
        assert call["messages"] == [{"role": "user", "content": [{"text": "q"}]}]
        assert (resp.text, resp.usage.output_tokens, resp.finish_reason) == ("nova", 6, "end_turn")
        assert provider.profile.name == "nova"
        await provider.aclose()

    async def test_no_system(self, profile: Profile, request_factory: RequestFactory) -> None:
        client = FakeBedrock({"output": {"message": {"content": []}}, "usage": {}})
        provider = BedrockConverseProvider(profile(), client=client)
        resp = await provider.generate(request_factory(system=None))
        assert "system" not in client.calls[0]
        assert resp.finish_reason == "unknown"

    @pytest.mark.parametrize(
        ("exc", "retryable", "status"),
        [
            (AwsError("ThrottlingException", 429), True, 429),
            (AwsError("ValidationException", 400), False, 400),
            (AwsError("AccessDeniedException", None), False, None),
            (RuntimeError("boom"), True, None),
        ],
    )
    async def test_errors(
        self,
        profile: Profile,
        request_factory: RequestFactory,
        exc: Exception,
        retryable: bool,
        status: int | None,
    ) -> None:
        provider = BedrockConverseProvider(profile(), client=FakeBedrock(exc))
        with pytest.raises(ProviderError) as info:
            await provider.generate(request_factory())
        assert info.value.retryable is retryable
        assert info.value.status_code == status

    async def test_malformed(self, profile: Profile, request_factory: RequestFactory) -> None:
        provider = BedrockConverseProvider(profile(), client=FakeBedrock({"output": {}}))
        with pytest.raises(ProviderError, match="malformed"):
            await provider.generate(request_factory())

    def test_from_region_builds_boto_client(self, profile: Profile) -> None:
        provider = BedrockConverseProvider.from_region(profile(), "us-east-1")
        assert provider.profile.name == "p1"
