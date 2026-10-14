"""OpenTelemetry setup and model-call instrumentation.

Attribute names follow the OpenTelemetry GenAI semantic conventions
(``gen_ai.*``) so traces and metrics line up with vendor dashboards.
"""

from __future__ import annotations

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from agentic_core.models.router import Attempt, AttemptOutcome
from agentic_core.models.types import ModelRequest, ModelResponse

INSTRUMENTATION = "agentic_core"


def configure_telemetry(
    *,
    service_name: str,
    service_version: str,
    environment: str,
    span_exporter: SpanExporter | None = None,
    metric_readers: list[MetricReader] | None = None,
) -> tuple[TracerProvider, MeterProvider]:
    """Install global tracer and meter providers.

    Exporters are injected so the same code ships OTLP in production and
    in-memory exporters in tests.
    """
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": service_version,
            "deployment.environment.name": environment,
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers or [])
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    return tracer_provider, meter_provider


class ModelTelemetryObserver:
    """RouterObserver that records GenAI metrics and span events."""

    def __init__(self, meter: metrics.Meter | None = None) -> None:
        meter = meter or metrics.get_meter(INSTRUMENTATION)
        self._tokens = meter.create_counter(
            "gen_ai.client.token.usage", unit="{token}", description="Tokens consumed"
        )
        self._duration = meter.create_histogram(
            "gen_ai.client.operation.duration", unit="s", description="Model call duration"
        )
        self._cost = meter.create_counter(
            "agentic.model.cost", unit="USD", description="Estimated model spend"
        )
        self._attempts = meter.create_counter(
            "agentic.model.attempts", unit="{attempt}", description="Provider attempts by outcome"
        )

    def on_attempt(self, request: ModelRequest, attempt: Attempt) -> None:
        self._attempts.add(
            1,
            {
                "gen_ai.system": attempt.provider,
                "outcome": attempt.outcome.value,
                "task": request.task,
            },
        )
        span = trace.get_current_span()
        if span.is_recording():
            span.add_event(
                "model.attempt",
                {
                    "gen_ai.system": attempt.provider,
                    "outcome": attempt.outcome.value,
                    "try": attempt.try_number,
                    "failed": attempt.outcome is AttemptOutcome.FAILED,
                },
            )

    def on_response(self, request: ModelRequest, response: ModelResponse) -> None:
        base = {
            "gen_ai.system": response.provider,
            "gen_ai.request.model": response.model,
            "task": request.task,
        }
        self._tokens.add(response.usage.input_tokens, {**base, "gen_ai.token.type": "input"})
        self._tokens.add(response.usage.output_tokens, {**base, "gen_ai.token.type": "output"})
        self._duration.record(response.latency_ms / 1000, base)
        self._cost.add(response.cost_usd, base)
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attributes(
                {
                    **base,
                    "gen_ai.usage.input_tokens": response.usage.input_tokens,
                    "gen_ai.usage.output_tokens": response.usage.output_tokens,
                    "gen_ai.response.finish_reasons": [response.finish_reason],
                }
            )
