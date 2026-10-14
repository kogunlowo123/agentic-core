# agentic-core

Shared kernel for the enterprise agentic AI platform repositories. Every
platform service (identity fabric, MCP/A2A gateway, control plane, clinical
orchestration, GxP runtime and the rest) depends on this package for the
same set of cross-cutting controls, so those controls are implemented and
tested once.

| Module | What it provides |
|---|---|
| `agentic_core.models` | Provider-neutral request/response contracts; adapters for Anthropic (Claude), any Chat Completions endpoint (OpenAI GPT, Azure OpenAI, Azure AI Foundry Phi, self-hosted Llama via vLLM/TGI/Ollama), Google Gemini (Gemini API and Vertex AI), and Amazon Bedrock Converse (Nova, Llama, Claude on Bedrock) |
| `agentic_core.models.router` | Classification-aware eligibility filtering, priority/cost/latency ordering, per-provider circuit breakers, retry with jittered exponential backoff, and failover |
| `agentic_core.policy` | Attribute-based policy engine with deny-overrides, human-approval outcomes, default deny, YAML policy sets and a policy digest recorded with every decision |
| `agentic_core.audit` | Hash-chained, Ed25519-signed audit events with pluggable sinks and an offline chain verifier |
| `agentic_core.security` | Prompt-injection heuristics, PII/PHI identifier detection and redaction, credential detection, and trust-aware isolation of untrusted content |
| `agentic_core.observability` | JSON logging with correlation IDs and sensitive-key scrubbing; OpenTelemetry tracing and GenAI metrics (tokens, duration, cost, attempts) |
| `agentic_core.domain` | SPIFFE-formatted agent identifiers, risk/trust/classification vocabularies, provenance records, error hierarchy |

## Install

```bash
uv add agentic-core                 # core
uv add "agentic-core[bedrock]"      # adds boto3 for Bedrock
uv add "agentic-core[otlp]"         # adds the OTLP gRPC exporter
```

Within this portfolio, sibling repositories reference it as a path source
until it is published to a package index:

```toml
[tool.uv.sources]
agentic-core = { path = "../agentic-core", editable = true }
```

## Usage

### Route a request across providers

```python
from agentic_core.domain.classification import DataClassification
from agentic_core.models import Message, ModelRequest, Role
from agentic_core.models.factory import ProvidersConfig, build_providers
from agentic_core.models.router import ModelRouter, RoutingStrategy
from agentic_core.observability import ModelTelemetryObserver

config = ProvidersConfig.from_file(Path("configs/providers.yaml"))  # resolves ${ENV} refs
router = ModelRouter(
    build_providers(config),
    strategy=RoutingStrategy.PRIORITY,
    observers=[ModelTelemetryObserver()],
)

routed = await router.generate(
    ModelRequest(
        messages=(
            Message(role=Role.SYSTEM, content="Summarize for a clinician."),
            Message(role=Role.USER, content=note_text),
        ),
        classification=DataClassification.RESTRICTED,
        task="summarize",
    )
)
print(routed.response.provider, routed.response.usage, routed.failed_over)
```

Only providers whose `max_classification` covers the request are eligible,
so restricted data never reaches a provider that has not been approved for
it, regardless of routing strategy or failover.

### Enforce a policy

```python
from agentic_core.policy import PolicyEngine, PolicyRequest, PolicySet, Resource, Subject

engine = PolicyEngine(PolicySet.from_file(Path("policies/agent-tools.yaml")))
decision = engine.enforce(
    PolicyRequest(
        subject=Subject(id=agent_id, roles=frozenset({"care-coordinator"})),
        action="tool:fhir.read",
        resource=Resource(type="fhir:Patient", id=patient_id),
    )
)
```

### Record and verify audit events

```python
from agentic_core.audit import AuditLog, JsonlAuditSink, verify_chain

log = AuditLog(JsonlAuditSink(Path("/var/audit/agent.jsonl")), signer, key_id="audit-2026-10")
await log.record(actor=agent_id, action="tool:fhir.read", resource=patient_ref, outcome="allow")

events = [e async for e in sink.read()]
verify_chain(events, {"audit-2026-10": public_key})
```

## Development

```bash
git clone <repo-url> && cd agentic-core
make install    # uv sync
make check      # format check, lint, type check, security scan, tests
```

No API keys, cloud credentials or network access to model vendors are
needed to build or run the test suite. Credentials are only read at runtime
when a service builds providers from `configs/providers.yaml`; the variables
it needs are listed in [configuration](docs/operations/configuration.md).

Quality gates enforced in CI: `ruff`, `black --check`, `mypy --strict`,
`bandit`, `pytest` with branch coverage of at least 90%.

## Documentation

- [Architecture](docs/architecture/overview.md)
- [Architecture decision records](docs/architecture/adr/)
- [Threat model](docs/security/threat-model.md)
- [Security policy](SECURITY.md)

## License

Apache-2.0
