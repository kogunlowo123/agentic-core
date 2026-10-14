"""Multi-provider model router with eligibility filtering, ordering and failover."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agentic_core.domain.errors import ProviderError, ProviderUnavailableError
from agentic_core.models.resilience import CircuitBreaker, LatencyTracker, RetryPolicy
from agentic_core.models.types import ModelProvider, ModelRequest, ModelResponse


class RoutingStrategy(StrEnum):
    PRIORITY = "priority"  # configured order
    COST = "cost"  # cheapest estimated cost first
    LATENCY = "latency"  # lowest observed EWMA latency first


class AttemptOutcome(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED_CIRCUIT_OPEN = "skipped_circuit_open"


class Attempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    outcome: AttemptOutcome
    try_number: int
    error: str | None = None


class RoutedResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    response: ModelResponse
    attempts: tuple[Attempt, ...]

    @property
    def failed_over(self) -> bool:
        return any(a.provider != self.response.provider for a in self.attempts)


class RouterObserver(Protocol):
    def on_attempt(self, request: ModelRequest, attempt: Attempt) -> None: ...

    def on_response(self, request: ModelRequest, response: ModelResponse) -> None: ...


Sleep = Callable[[float], Awaitable[None]]


class ModelRouter:
    def __init__(
        self,
        providers: Sequence[ModelProvider],
        *,
        strategy: RoutingStrategy = RoutingStrategy.PRIORITY,
        retry: RetryPolicy | None = None,
        breaker_factory: Callable[[], CircuitBreaker] = CircuitBreaker,
        observers: Sequence[RouterObserver] = (),
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        names = [p.profile.name for p in providers]
        if not providers:
            raise ValueError("router needs at least one provider")
        if len(set(names)) != len(names):
            raise ValueError("provider names must be unique")
        self._providers = list(providers)
        self._strategy = strategy
        self._retry = retry or RetryPolicy()
        self._breakers = {n: breaker_factory() for n in names}
        self._latency = {n: LatencyTracker() for n in names}
        self._observers = list(observers)
        self._sleep = sleep

    def breaker(self, provider: str) -> CircuitBreaker:
        return self._breakers[provider]

    def plan(self, request: ModelRequest) -> list[ModelProvider]:
        """Eligible providers in the order they will be tried."""
        eligible = [p for p in self._providers if p.profile.serves(request)]
        if self._strategy is RoutingStrategy.COST:
            expected_in = sum(len(m.content) for m in request.messages) // 4
            eligible.sort(key=lambda p: p.profile.estimate_cost(expected_in, request.max_tokens))
        elif self._strategy is RoutingStrategy.LATENCY:
            # Providers with no observations go first so they get measured.
            eligible.sort(key=lambda p: self._latency[p.profile.name].value or 0.0)
        return eligible

    async def generate(self, request: ModelRequest) -> RoutedResponse:
        plan = self.plan(request)
        if not plan:
            raise ProviderUnavailableError(
                f"no provider is approved for classification={request.classification.name} "
                f"task={request.task}",
                attempts=[],
            )
        attempts: list[Attempt] = []
        for provider in plan:
            name = provider.profile.name
            breaker = self._breakers[name]
            for try_number in range(1, self._retry.max_attempts + 1):
                if not breaker.allow():
                    self._record(
                        request,
                        attempts,
                        Attempt(
                            provider=name,
                            outcome=AttemptOutcome.SKIPPED_CIRCUIT_OPEN,
                            try_number=try_number,
                        ),
                    )
                    break
                try:
                    response = await provider.generate(request)
                except ProviderError as exc:
                    breaker.record_failure()
                    self._record(
                        request,
                        attempts,
                        Attempt(
                            provider=name,
                            outcome=AttemptOutcome.FAILED,
                            try_number=try_number,
                            error=f"{exc.code}:{exc.status_code or ''}:{exc}",
                        ),
                    )
                    if not exc.retryable or try_number == self._retry.max_attempts:
                        break
                    await self._sleep(self._retry.delay(try_number))
                    continue
                breaker.record_success()
                self._latency[name].observe(response.latency_ms)
                self._record(
                    request,
                    attempts,
                    Attempt(provider=name, outcome=AttemptOutcome.SUCCESS, try_number=try_number),
                )
                for observer in self._observers:
                    observer.on_response(request, response)
                return RoutedResponse(response=response, attempts=tuple(attempts))
        raise ProviderUnavailableError(
            f"all {len(plan)} eligible providers failed",
            attempts=[f"{a.provider}#{a.try_number}:{a.outcome}" for a in attempts],
        )

    def _record(self, request: ModelRequest, attempts: list[Attempt], attempt: Attempt) -> None:
        attempts.append(attempt)
        for observer in self._observers:
            observer.on_attempt(request, attempt)

    async def aclose(self) -> None:
        await asyncio.gather(*(p.aclose() for p in self._providers))
