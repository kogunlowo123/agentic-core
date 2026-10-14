"""Provider-neutral request and response contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentic_core.domain.classification import DataClassification, TrustLevel
from agentic_core.domain.identifiers import new_id


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str
    trust: TrustLevel = TrustLevel.USER


class ModelRequest(BaseModel):
    """A single completion request, independent of any vendor API."""

    model_config = ConfigDict(frozen=True)

    request_id: str = Field(default_factory=new_id)
    messages: tuple[Message, ...] = Field(min_length=1)
    max_tokens: int = Field(default=1024, ge=1, le=200_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    classification: DataClassification = DataClassification.INTERNAL
    task: str = Field(default="general", description="Routing hint, e.g. summarize, code")

    @model_validator(mode="after")
    def _conversation_shape(self) -> ModelRequest:
        if not any(m.role is not Role.SYSTEM for m in self.messages):
            raise ValueError("request needs at least one user or assistant message")
        return self

    @property
    def system_prompt(self) -> str | None:
        parts = [m.content for m in self.messages if m.role is Role.SYSTEM]
        return "\n\n".join(parts) if parts else None

    @property
    def conversation(self) -> tuple[Message, ...]:
        return tuple(m for m in self.messages if m.role is not Role.SYSTEM)


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    provider: str
    model: str
    text: str
    finish_reason: str
    usage: TokenUsage
    latency_ms: float = Field(ge=0)
    cost_usd: float = Field(default=0.0, ge=0)


class ProviderProfile(BaseModel):
    """Operator-supplied facts about a provider deployment.

    Prices are configuration, not constants: contracted rates differ by
    customer and change over time, so they must come from configuration.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    model: str
    max_classification: DataClassification = DataClassification.INTERNAL
    input_cost_per_mtok: float = Field(default=0.0, ge=0)
    output_cost_per_mtok: float = Field(default=0.0, ge=0)
    max_context_tokens: int = Field(default=128_000, ge=1)
    tasks: frozenset[str] = frozenset({"general"})
    region: str | None = None

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_cost_per_mtok + output_tokens * self.output_cost_per_mtok
        ) / 1_000_000

    def serves(self, request: ModelRequest) -> bool:
        return request.classification <= self.max_classification and (
            request.task in self.tasks or "general" in self.tasks
        )


@runtime_checkable
class ModelProvider(Protocol):
    """Adapter contract every vendor integration implements."""

    @property
    def profile(self) -> ProviderProfile: ...

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    async def aclose(self) -> None: ...
