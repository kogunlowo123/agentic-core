# ADR-0004: Hash-chained, signed audit events

- Status: Accepted
- Date: 2026-10-14

## Context

Regulated deployments (HIPAA, SOC 2, GxP under 21 CFR Part 11) need audit
trails that show who did what, when, under which policy, and that the trail
has not been altered. Storage-level immutability (S3 Object Lock, Azure
immutable blobs, GCS bucket lock) protects against deletion but not against
a process with write access appending forged history before it lands.

## Decision

Each `AuditEvent` carries the SHA-256 hash of its predecessor and its own
hash over a canonical JSON body. The event hash is signed with Ed25519. The
signer is an interface so production deployments can use a KMS or HSM key;
`key_id` is stored per event so keys can rotate without breaking
verification. `AuditLog` serializes appends with an async lock so sequence
numbers and links stay consistent under concurrency, and resumes from the
sink tail after restart.

`verify_chain` detects altered content, deleted, inserted and reordered
events, re-hashed forgeries and unknown or wrong keys.

## Consequences

- Appends are serialized per log instance. Services that need higher write
  throughput shard logs (for example per agent) and anchor each shard head
  periodically into a shared chain.
- The JSONL sink is for development and single-node use. Production sinks
  write to WORM object storage or an append-only database table; they
  implement the same `AuditSink` protocol.
