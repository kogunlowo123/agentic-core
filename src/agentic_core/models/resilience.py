"""Circuit breaker and retry policy used by the model router."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Consecutive-failure circuit breaker with a single half-open probe."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        reset_timeout_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self._threshold = failure_threshold
        self._reset_timeout = reset_timeout_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return BreakerState.CLOSED
        if self._clock() - self._opened_at >= self._reset_timeout:
            return BreakerState.HALF_OPEN
        return BreakerState.OPEN

    def allow(self) -> bool:
        state = self.state
        if state is BreakerState.CLOSED:
            return True
        if state is BreakerState.HALF_OPEN and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self._probe_in_flight = False
        if self._opened_at is not None:
            # A failed half-open probe re-opens the circuit for a full timeout.
            self._opened_at = self._clock()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._opened_at = self._clock()


class RetryPolicy(BaseModel):
    """Exponential backoff with full jitter."""

    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_s: float = Field(default=0.25, ge=0)
    max_delay_s: float = Field(default=8.0, ge=0)

    def delay(self, attempt: int, rng: random.Random | None = None) -> float:
        """Delay before retry number ``attempt`` (1-based)."""
        ceiling = min(self.max_delay_s, self.base_delay_s * (2 ** (attempt - 1)))
        return (rng or random.SystemRandom()).uniform(0, ceiling)


class LatencyTracker:
    """Exponentially weighted moving average of observed latency."""

    def __init__(self, alpha: float = 0.2) -> None:
        if not 0 < alpha <= 1:
            raise ValueError("alpha must be in (0, 1]")
        self._alpha = alpha
        self._value: float | None = None

    @property
    def value(self) -> float | None:
        return self._value

    def observe(self, latency_ms: float) -> None:
        if self._value is None:
            self._value = latency_ms
        else:
            self._value = self._alpha * latency_ms + (1 - self._alpha) * self._value
