from __future__ import annotations

import json
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentic_core.models.router import Attempt, AttemptOutcome
from agentic_core.models.types import Message, ModelRequest, ModelResponse, Role, TokenUsage
from agentic_core.observability import (
    ModelTelemetryObserver,
    bind_correlation_id,
    configure_logging,
    configure_telemetry,
    correlation_id,
    get_logger,
)
from agentic_core.observability.logging import scrub_sensitive


class TestLogging:
    def test_json_with_correlation_and_scrubbing(self, capsys: pytest.CaptureFixture[str]) -> None:
        configure_logging(service="svc", environment="test", level="debug")
        log = get_logger("t")
        with bind_correlation_id("corr-1") as cid:
            assert cid == correlation_id() == "corr-1"
            log.info("call", api_key="sk-secret", headers={"Authorization": "Bearer x", "k": 1})
        assert correlation_id() is None
        line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert line["correlation_id"] == "corr-1"
        assert line["service"] == "svc"
        assert line["api_key"] == "[REDACTED]"
        assert line["headers"] == {"Authorization": "[REDACTED]", "k": 1}

    def test_generated_correlation_id(self) -> None:
        with bind_correlation_id() as cid:
            assert len(cid) == 32

    def test_nested_scrub(self) -> None:
        event: dict[str, Any] = {"outer": {"inner": {"token": "t"}}, "x": 1}
        assert scrub_sensitive(None, "", event) == {
            "outer": {"inner": {"token": "[REDACTED]"}},
            "x": 1,
        }


def _request() -> ModelRequest:
    return ModelRequest(messages=(Message(role=Role.USER, content="q"),), task="summarize")


def _response() -> ModelResponse:
    return ModelResponse(
        request_id="r",
        provider="anthropic",
        model="claude",
        text="a",
        finish_reason="end_turn",
        usage=TokenUsage(input_tokens=10, output_tokens=4),
        latency_ms=250,
        cost_usd=0.01,
    )


class TestTelemetry:
    def test_metrics_and_span_attributes(self) -> None:
        reader = InMemoryMetricReader()
        meter = MeterProvider(metric_readers=[reader]).get_meter("t")
        exporter = InMemorySpanExporter()
        tracer_provider = TracerProvider()
        tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = tracer_provider.get_tracer("t")

        observer = ModelTelemetryObserver(meter)
        with tracer.start_as_current_span("generate"):
            observer.on_attempt(
                _request(),
                Attempt(provider="anthropic", outcome=AttemptOutcome.FAILED, try_number=1),
            )
            observer.on_response(_request(), _response())

        data = reader.get_metrics_data()
        assert data is not None
        metrics = {
            m.name: m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
        }
        tokens = {
            p.attributes["gen_ai.token.type"]: p.value
            for p in metrics["gen_ai.client.token.usage"].data.data_points
        }
        assert tokens == {"input": 10, "output": 4}
        assert metrics["agentic.model.attempts"].data.data_points[0].attributes["outcome"] == (
            "failed"
        )
        assert "gen_ai.client.operation.duration" in metrics
        assert "agentic.model.cost" in metrics

        (span,) = exporter.get_finished_spans()
        assert span.attributes is not None
        assert span.attributes["gen_ai.usage.output_tokens"] == 4
        assert span.events[0].name == "model.attempt"

    def test_no_span_is_safe(self) -> None:
        observer = ModelTelemetryObserver(MeterProvider().get_meter("t"))
        assert not trace.get_current_span().is_recording()
        observer.on_attempt(
            _request(), Attempt(provider="a", outcome=AttemptOutcome.SUCCESS, try_number=1)
        )
        observer.on_response(_request(), _response())

    def test_configure_telemetry(self) -> None:
        tracer_provider, meter_provider = configure_telemetry(
            service_name="svc",
            service_version="1.0",
            environment="test",
            span_exporter=InMemorySpanExporter(),
            metric_readers=[InMemoryMetricReader()],
        )
        assert tracer_provider.resource.attributes["service.name"] == "svc"
        ModelTelemetryObserver()  # uses global meter
        tracer_provider.shutdown()
        meter_provider.shutdown()
