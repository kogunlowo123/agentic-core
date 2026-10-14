from __future__ import annotations

import httpx
import pytest

from agentic_core.models.factory import ProvidersConfig, build_provider, build_providers
from agentic_core.models.providers import (
    AnthropicProvider,
    BedrockConverseProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
)

CONFIG = """
providers:
  - kind: anthropic
    api_key_env: ANTHROPIC_API_KEY
    profile: {name: claude, model: claude-opus-5-5, max_classification: 3, tasks: [general]}
  - kind: openai_compatible
    base_url: https://my-resource.openai.azure.com
    path: /openai/deployments/gpt/chat/completions
    query: {api-version: "2024-10-21"}
    auth: api-key
    api_key_env: AZURE_OPENAI_KEY
    send_model: false
    profile: {name: azure-gpt, model: gpt}
  - kind: openai_compatible
    base_url: http://vllm.inference.svc:8000
    auth: none
    profile: {name: llama, model: meta-llama/Llama-3.3-70B-Instruct}
  - kind: gemini
    access_token_env: GCP_ACCESS_TOKEN
    base_url: https://us-central1-aiplatform.googleapis.com/v1/projects/p/locations/us-central1/publishers/google
    profile: {name: gemini, model: gemini-2.5-pro}
  - kind: bedrock
    profile: {name: nova, model: amazon.nova-pro-v1:0, region: us-east-1}
"""

ENV = {"ANTHROPIC_API_KEY": "a", "AZURE_OPENAI_KEY": "b", "GCP_ACCESS_TOKEN": "c"}


def test_builds_every_kind() -> None:
    providers = build_providers(ProvidersConfig.from_yaml(CONFIG), env=ENV)
    assert [type(p) for p in providers] == [
        AnthropicProvider,
        OpenAICompatibleProvider,
        OpenAICompatibleProvider,
        GeminiProvider,
        BedrockConverseProvider,
    ]


def test_missing_env_var() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is not set"):
        build_providers(ProvidersConfig.from_yaml(CONFIG), env={})


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("providers: [{kind: anthropic, profile: {name: a, model: m}}]", "api_key_env"),
        ("providers: [{kind: openai_compatible, profile: {name: a, model: m}}]", "base_url"),
        ("providers: [{kind: bedrock, profile: {name: a, model: m}}]", "region"),
    ],
)
def test_required_fields(yaml_text: str, message: str) -> None:
    spec = ProvidersConfig.from_yaml(yaml_text).providers[0]
    with pytest.raises(ValueError, match=message):
        build_provider(spec, env={}, transport=httpx.MockTransport(lambda r: httpx.Response(200)))


def test_rejects_inline_secrets() -> None:
    with pytest.raises(ValueError, match="api_key"):
        ProvidersConfig.from_yaml(
            "providers: [{kind: anthropic, api_key: sk-x, profile: {name: a, model: m}}]"
        )
