from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agentic_core.domain.classification import DataClassification
from agentic_core.models.types import Message, ModelRequest, ProviderProfile, Role


@pytest.fixture
def profile() -> Callable[..., ProviderProfile]:
    def make(name: str = "p1", **overrides: Any) -> ProviderProfile:
        values: dict[str, Any] = {
            "name": name,
            "model": f"{name}-model",
            "max_classification": DataClassification.RESTRICTED,
            "input_cost_per_mtok": 1.0,
            "output_cost_per_mtok": 2.0,
        }
        values.update(overrides)
        return ProviderProfile(**values)

    return make


@pytest.fixture
def request_factory() -> Callable[..., ModelRequest]:
    def make(text: str = "hello", *, system: str | None = "be brief", **kw: Any) -> ModelRequest:
        messages = []
        if system:
            messages.append(Message(role=Role.SYSTEM, content=system))
        messages.append(Message(role=Role.USER, content=text))
        return ModelRequest(messages=tuple(messages), **kw)

    return make


class Recorder:
    """httpx MockTransport handler that records requests and replays responses."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def json(self, index: int = -1) -> Any:
        return json.loads(self.requests[index].content)
