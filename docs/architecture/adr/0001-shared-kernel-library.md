# ADR-0001: Ship cross-cutting controls as an in-process library

- Status: Accepted
- Date: 2026-10-14

## Context

Twelve platform services need the same model access, policy, audit,
content-security and telemetry behaviour. Options considered:

1. Copy the controls into each service.
2. Run them as a shared network service (sidecar or central API).
3. Ship them as a versioned library that each service embeds.

Copying guarantees drift. A central service adds a network hop and a shared
failure domain to every model call and every policy check, and it becomes a
high-value target that sees every prompt.

## Decision

Ship the controls as the `agentic-core` Python library. Services pin a
version. Centralised concerns that genuinely need a network boundary
(identity issuance, tool gateway, control plane) are separate services that
themselves use this library.

Because it is a library, this repository uses a `src/agentic_core/<module>`
layout instead of the service template's `src/api`, `src/domain` and so on,
and it has no Dockerfile, Helm chart or Terraform. Those artifacts live in
the service repositories.

## Consequences

- One implementation of each control, tested once to a 90% branch coverage
  floor.
- Upgrades require a dependency bump per service; Dependabot and the
  portfolio CI matrix make this routine.
- Policy and provider configuration remain per-service data, loaded at
  start-up, so the library carries no tenant data.
