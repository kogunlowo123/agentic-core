"""Latency budgets for controls that run on every request.

Budgets are deliberately loose so they hold on shared CI runners; they exist
to catch order-of-magnitude regressions such as catastrophic regex
backtracking, not to benchmark.
"""

from __future__ import annotations

import time

import pytest

from agentic_core.domain.classification import TrustLevel
from agentic_core.models.types import Message, ModelRequest, Role
from agentic_core.policy import PolicyEngine, PolicyRequest, PolicySet, Resource, Subject
from agentic_core.security import ContentGuard, PromptInjectionDetector
from tests.unit.test_policy import POLICY_YAML

pytestmark = pytest.mark.performance

DOCUMENT = (
    "Patient presented with chest pain radiating to the left arm. Troponin elevated. "
    "Cardiology consulted. Contact the care team at team@example.org. "
) * 200  # ~30 KB


def test_guard_budget() -> None:
    guard = ContentGuard()
    request = ModelRequest(
        messages=(
            Message(role=Role.USER, content="Summarize."),
            Message(role=Role.USER, content=DOCUMENT, trust=TrustLevel.EXTERNAL),
        )
    )
    started = time.perf_counter()
    for _ in range(20):
        guard.inspect_request(request)
    per_call_ms = (time.perf_counter() - started) * 1000 / 20
    assert per_call_ms < 250


@pytest.mark.parametrize(
    "adversarial",
    [
        "ignore " * 5000,
        "a" * 50_000 + "!",
        "-" * 10_000 + "BEGIN PRIVATE KEY",
        "x@" * 10_000,
    ],
    ids=["repeated-keyword", "long-run", "dash-run", "at-run"],
)
def test_no_catastrophic_backtracking(adversarial: str) -> None:
    started = time.perf_counter()
    PromptInjectionDetector().assess(adversarial)
    ContentGuard().inspect_output(adversarial)
    assert time.perf_counter() - started < 2.0


def test_policy_budget() -> None:
    engine = PolicyEngine(PolicySet.from_yaml(POLICY_YAML))
    request = PolicyRequest(
        subject=Subject(id="a", roles=frozenset({"care-coordinator"})),
        action="tool:fhir.read",
        resource=Resource(type="fhir:Patient", attributes={"care_team": ["team-a"]}),
        environment={"business_hours": True},
    )
    started = time.perf_counter()
    for _ in range(2000):
        engine.evaluate(request)
    per_call_us = (time.perf_counter() - started) * 1_000_000 / 2000
    assert per_call_us < 500
