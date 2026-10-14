# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-14

### Added

- Provider-neutral model contracts and adapters for Anthropic Messages,
  Chat Completions (OpenAI, Azure OpenAI, Azure AI Foundry, vLLM/TGI/Ollama),
  Gemini (Gemini API and Vertex AI) and Bedrock Converse.
- Model router with classification gating, priority/cost/latency strategies,
  circuit breakers, jittered retries and failover.
- Declarative provider configuration that references credentials by
  environment variable name only.
- ABAC policy engine with deny-overrides, approval outcomes, default deny
  and policy digests.
- Hash-chained Ed25519-signed audit log with JSONL and in-memory sinks and a
  chain verifier.
- Prompt-injection heuristics, PII/PHI identifier and credential detection,
  redaction, and untrusted-content isolation.
- JSON logging with correlation IDs and key scrubbing; OpenTelemetry GenAI
  metrics and span attributes.
