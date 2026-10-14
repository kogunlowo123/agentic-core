"""Build providers from declarative configuration.

Configuration names the environment variable that holds a credential, never
the credential itself, so provider config files can be committed and
reviewed. In Kubernetes those variables are populated from a secret store
(External Secrets Operator, CSI Secrets Store) or replaced entirely by
workload identity.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal

import httpx
import yaml
from pydantic import BaseModel, ConfigDict

from agentic_core.models.providers.anthropic import AnthropicProvider
from agentic_core.models.providers.bedrock import BedrockConverseProvider
from agentic_core.models.providers.gemini import GeminiProvider
from agentic_core.models.providers.openai_compatible import OpenAICompatibleProvider
from agentic_core.models.types import ModelProvider, ProviderProfile


class ProviderKind(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"
    GEMINI = "gemini"
    BEDROCK = "bedrock"


class ProviderSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProviderKind
    profile: ProviderProfile
    base_url: str | None = None
    api_key_env: str | None = None
    access_token_env: str | None = None
    auth: Literal["bearer", "api-key", "none"] = "bearer"
    path: str | None = None
    query: dict[str, str] | None = None
    max_tokens_field: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    send_model: bool = True
    region: str | None = None
    timeout_s: float = 60.0


_ENV_REF = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


def env_references(text: str) -> set[str]:
    """Variable names referenced as ``${NAME}`` outside full-line YAML comments."""
    return {
        m.group(1)
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
        for m in _ENV_REF.finditer(line)
    }


def expand_env(text: str, env: Mapping[str, str]) -> str:
    """Substitute ``${NAME}`` references; fail closed when any is unset or empty."""
    missing = sorted(name for name in env_references(text) if not env.get(name))
    if missing:
        raise ValueError(f"unset environment variables in provider config: {missing}")
    return "\n".join(
        line if line.lstrip().startswith("#") else _ENV_REF.sub(lambda m: env[m.group(1)], line)
        for line in text.splitlines()
    )


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    providers: tuple[ProviderSpec, ...]

    @classmethod
    def from_yaml(cls, text: str, *, env: Mapping[str, str] | None = None) -> ProvidersConfig:
        """Parse provider config.

        Deployment-specific values (endpoints, project IDs, contracted prices)
        are written as ``${NAME}`` and resolved from the environment, so the
        same file is committed once and deployed everywhere.
        """
        resolved = expand_env(text, os.environ if env is None else env)
        return cls.model_validate(yaml.safe_load(resolved))

    @classmethod
    def from_file(cls, path: Path, *, env: Mapping[str, str] | None = None) -> ProvidersConfig:
        return cls.from_yaml(path.read_text(encoding="utf-8"), env=env)


def _secret(name: str | None, env: Mapping[str, str], provider: str) -> str | None:
    if name is None:
        return None
    value = env.get(name)
    if not value:
        raise ValueError(f"{provider}: environment variable {name} is not set")
    return value


def build_provider(
    spec: ProviderSpec,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ModelProvider:
    env = os.environ if env is None else env
    name = spec.profile.name
    match spec.kind:
        case ProviderKind.ANTHROPIC:
            key = _secret(spec.api_key_env, env, name)
            if key is None:
                raise ValueError(f"{name}: api_key_env is required")
            return AnthropicProvider(
                spec.profile,
                api_key=key,
                base_url=spec.base_url or "https://api.anthropic.com",
                timeout_s=spec.timeout_s,
                transport=transport,
            )
        case ProviderKind.OPENAI_COMPATIBLE:
            if spec.base_url is None:
                raise ValueError(f"{name}: base_url is required")
            return OpenAICompatibleProvider(
                spec.profile,
                base_url=spec.base_url,
                api_key=_secret(spec.api_key_env, env, name),
                auth=spec.auth,
                path=spec.path or "/v1/chat/completions",
                query=spec.query,
                max_tokens_field=spec.max_tokens_field,
                send_model=spec.send_model,
                timeout_s=spec.timeout_s,
                transport=transport,
            )
        case ProviderKind.GEMINI:
            return GeminiProvider(
                spec.profile,
                api_key=_secret(spec.api_key_env, env, name),
                access_token=_secret(spec.access_token_env, env, name),
                base_url=spec.base_url or "https://generativelanguage.googleapis.com/v1beta",
                timeout_s=spec.timeout_s,
                transport=transport,
            )
        case ProviderKind.BEDROCK:
            region = spec.region or spec.profile.region
            if region is None:
                raise ValueError(f"{name}: region is required for bedrock")
            return BedrockConverseProvider.from_region(spec.profile, region)
    raise ValueError(f"unsupported provider kind {spec.kind}")  # pragma: no cover


def build_providers(
    config: ProvidersConfig,
    *,
    env: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Sequence[ModelProvider]:
    return [build_provider(s, env=env, transport=transport) for s in config.providers]
