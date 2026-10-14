"""Fault injection: random provider failures must never violate router invariants."""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentic_core.domain.classification import DataClassification
from agentic_core.domain.errors import ProviderError, ProviderUnavailableError
from agentic_core.models.router import ModelRouter
from agentic_core.models.types import Message, ModelRequest, ProviderProfile, Role
from tests.unit.test_router import ScriptedProvider, no_sleep

pytestmark = pytest.mark.chaos

outcome = st.one_of(
    st.floats(min_value=1, max_value=500),
    st.builds(
        lambda retryable, status: ProviderError(
            "fault", provider="x", status_code=status, retryable=retryable
        ),
        st.booleans(),
        st.sampled_from([429, 500, 503, 400]),
    ),
)

provider_spec = st.tuples(
    st.lists(outcome, min_size=1, max_size=6),
    st.sampled_from(list(DataClassification)),
)


@settings(max_examples=150, deadline=None)
@given(
    specs=st.lists(provider_spec, min_size=1, max_size=5),
    classification=st.sampled_from(list(DataClassification)),
)
def test_router_invariants(
    specs: list[tuple[list[ProviderError | float], DataClassification]],
    classification: DataClassification,
) -> None:
    providers = [
        ScriptedProvider(
            ProviderProfile(name=f"p{i}", model="m", max_classification=max_cls), script
        )
        for i, (script, max_cls) in enumerate(specs)
    ]
    router = ModelRouter(providers, sleep=no_sleep)
    request = ModelRequest(
        messages=(Message(role=Role.USER, content="q"),), classification=classification
    )

    try:
        routed = asyncio.run(router.generate(request))
    except ProviderUnavailableError:
        # Acceptable only if no eligible provider produced a success.
        return

    chosen = next(p for p in providers if p.profile.name == routed.response.provider)
    # Invariant 1: data never reaches a provider not approved for its classification.
    assert chosen.profile.max_classification >= classification
    for p in providers:
        if p.profile.max_classification < classification:
            assert p.calls == 0
    # Invariant 2: the last attempt is the success and belongs to the chosen provider.
    assert routed.attempts[-1].provider == chosen.profile.name
