from __future__ import annotations

import random
from collections.abc import Callable

import pytest

from agentic_core.domain.classification import DataClassification
from agentic_core.domain.errors import ProviderError, ProviderUnavailableError
from agentic_core.models.resilience import (
    BreakerState,
    CircuitBreaker,
    LatencyTracker,
    RetryPolicy,
)
from agentic_core.models.router import (
    Attempt,
    AttemptOutcome,
    ModelRouter,
    RoutingStrategy,
)
from agentic_core.models.types import ModelRequest, ModelResponse, ProviderProfile, TokenUsage

Profile = Callable[..., ProviderProfile]
RequestFactory = Callable[..., ModelRequest]


class ScriptedProvider:
    """Provider whose outcomes are scripted: ProviderError or a latency (float)."""

    def __init__(self, profile: ProviderProfile, script: list[ProviderError | float]) -> None:
        self._profile = profile
        self.script = script
        self.calls = 0
        self.closed = False

    @property
    def profile(self) -> ProviderProfile:
        return self._profile

    async def generate(self, request: ModelRequest) -> ModelResponse:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        if isinstance(step, ProviderError):
            raise step
        return ModelResponse(
            request_id=request.request_id,
            provider=self._profile.name,
            model=self._profile.model,
            text=f"from {self._profile.name}",
            finish_reason="stop",
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            latency_ms=step,
        )

    async def aclose(self) -> None:
        self.closed = True


def err(name: str, *, retryable: bool = True) -> ProviderError:
    return ProviderError("x", provider=name, status_code=503, retryable=retryable)


async def no_sleep(_: float) -> None:
    return None


class Observer:
    def __init__(self) -> None:
        self.attempts: list[Attempt] = []
        self.responses: list[ModelResponse] = []

    def on_attempt(self, request: ModelRequest, attempt: Attempt) -> None:
        self.attempts.append(attempt)

    def on_response(self, request: ModelRequest, response: ModelResponse) -> None:
        self.responses.append(response)


class TestRouter:
    async def test_primary_success(self, profile: Profile, request_factory: RequestFactory) -> None:
        a = ScriptedProvider(profile("a"), [10.0])
        router = ModelRouter([a, ScriptedProvider(profile("b"), [10.0])], sleep=no_sleep)
        routed = await router.generate(request_factory())
        assert routed.response.provider == "a"
        assert not routed.failed_over

    async def test_retry_then_failover(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        a = ScriptedProvider(profile("a"), [err("a")])
        b = ScriptedProvider(profile("b"), [5.0])
        observer = Observer()
        router = ModelRouter(
            [a, b],
            retry=RetryPolicy(max_attempts=2, base_delay_s=0),
            observers=[observer],
            sleep=no_sleep,
        )
        routed = await router.generate(request_factory())
        assert routed.response.provider == "b"
        assert routed.failed_over
        assert a.calls == 2
        assert [x.outcome for x in routed.attempts] == [
            AttemptOutcome.FAILED,
            AttemptOutcome.FAILED,
            AttemptOutcome.SUCCESS,
        ]
        assert observer.attempts == list(routed.attempts)
        assert observer.responses == [routed.response]

    async def test_non_retryable_fails_over_immediately(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        a = ScriptedProvider(profile("a"), [err("a", retryable=False)])
        b = ScriptedProvider(profile("b"), [5.0])
        router = ModelRouter([a, b], sleep=no_sleep)
        await router.generate(request_factory())
        assert a.calls == 1

    async def test_all_fail(self, profile: Profile, request_factory: RequestFactory) -> None:
        router = ModelRouter(
            [ScriptedProvider(profile("a"), [err("a", retryable=False)])], sleep=no_sleep
        )
        with pytest.raises(ProviderUnavailableError, match="all 1") as info:
            await router.generate(request_factory())
        assert info.value.attempts == ["a#1:failed"]

    async def test_classification_gate(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        public_only = ScriptedProvider(
            profile("public", max_classification=DataClassification.INTERNAL), [1.0]
        )
        approved = ScriptedProvider(profile("approved"), [1.0])
        router = ModelRouter([public_only, approved], sleep=no_sleep)
        routed = await router.generate(
            request_factory(classification=DataClassification.RESTRICTED)
        )
        assert routed.response.provider == "approved"
        assert public_only.calls == 0

    async def test_no_eligible_provider(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        router = ModelRouter(
            [ScriptedProvider(profile("a", tasks=frozenset({"code"})), [1.0])], sleep=no_sleep
        )
        with pytest.raises(ProviderUnavailableError, match="no provider is approved"):
            await router.generate(request_factory(task="summarize"))

    def test_cost_strategy(self, profile: Profile, request_factory: RequestFactory) -> None:
        dear = ScriptedProvider(profile("dear", output_cost_per_mtok=50.0), [1.0])
        cheap = ScriptedProvider(profile("cheap", output_cost_per_mtok=0.5), [1.0])
        router = ModelRouter([dear, cheap], strategy=RoutingStrategy.COST)
        assert [p.profile.name for p in router.plan(request_factory())] == ["cheap", "dear"]

    async def test_latency_strategy_learns(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        slow = ScriptedProvider(profile("slow"), [900.0])
        fast = ScriptedProvider(profile("fast"), [20.0])
        router = ModelRouter([slow, fast], strategy=RoutingStrategy.LATENCY, sleep=no_sleep)
        await router.generate(request_factory())  # slow measured (both unobserved, stable order)
        assert [p.profile.name for p in router.plan(request_factory())] == ["fast", "slow"]
        await router.generate(request_factory())  # fast measured
        assert [p.profile.name for p in router.plan(request_factory())] == ["fast", "slow"]

    async def test_open_circuit_is_skipped(
        self, profile: Profile, request_factory: RequestFactory
    ) -> None:
        a = ScriptedProvider(profile("a"), [err("a", retryable=False)])
        b = ScriptedProvider(profile("b"), [1.0])
        router = ModelRouter(
            [a, b],
            breaker_factory=lambda: CircuitBreaker(failure_threshold=1, reset_timeout_s=60),
            sleep=no_sleep,
        )
        await router.generate(request_factory())
        assert router.breaker("a").state is BreakerState.OPEN
        routed = await router.generate(request_factory())
        assert routed.attempts[0].outcome is AttemptOutcome.SKIPPED_CIRCUIT_OPEN
        assert a.calls == 1

    def test_construction_validation(self, profile: Profile) -> None:
        with pytest.raises(ValueError, match="at least one"):
            ModelRouter([])
        with pytest.raises(ValueError, match="unique"):
            ModelRouter(
                [ScriptedProvider(profile("a"), [1.0]), ScriptedProvider(profile("a"), [1.0])]
            )

    async def test_aclose(self, profile: Profile) -> None:
        a = ScriptedProvider(profile("a"), [1.0])
        await ModelRouter([a]).aclose()
        assert a.closed


class TestCircuitBreaker:
    def test_lifecycle(self) -> None:
        now = [0.0]
        breaker = CircuitBreaker(failure_threshold=2, reset_timeout_s=10, clock=lambda: now[0])
        assert breaker.allow()
        breaker.record_failure()
        assert breaker.state is BreakerState.CLOSED
        breaker.record_failure()
        assert breaker.state is BreakerState.OPEN
        assert not breaker.allow()
        now[0] = 10.0
        assert breaker.state is BreakerState.HALF_OPEN
        assert breaker.allow()  # single probe
        assert not breaker.allow()
        breaker.record_failure()  # failed probe re-opens
        assert breaker.state is BreakerState.OPEN
        now[0] = 20.0
        assert breaker.allow()
        breaker.record_success()
        assert breaker.state is BreakerState.CLOSED

    def test_threshold_validation(self) -> None:
        with pytest.raises(ValueError, match=">= 1"):
            CircuitBreaker(failure_threshold=0)


class TestRetryAndLatency:
    def test_backoff_bounded(self) -> None:
        policy = RetryPolicy(base_delay_s=1, max_delay_s=3)
        rng = random.Random(7)  # noqa: S311 - deterministic test RNG
        for attempt in range(1, 8):
            assert 0 <= policy.delay(attempt, rng) <= min(3, 2 ** (attempt - 1))
        assert policy.delay(1) <= 1

    def test_ewma(self) -> None:
        tracker = LatencyTracker(alpha=0.5)
        assert tracker.value is None
        tracker.observe(100)
        tracker.observe(200)
        assert tracker.value == 150
        with pytest.raises(ValueError, match="alpha"):
            LatencyTracker(alpha=0)
