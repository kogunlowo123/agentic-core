# ADR-0005: Treat injection detection as one layer, not the boundary

- Status: Accepted
- Date: 2026-10-14

## Context

No classifier, heuristic or model reliably detects every prompt injection.
Systems that rely on detection alone fail open on the first novel phrasing.

## Decision

Defence is layered, and the boundary is architectural:

1. **Trust labels.** Every `Message` carries a `TrustLevel`. Retrieved
   documents, web content and tool output are `EXTERNAL`.
2. **Isolation.** `EXTERNAL` content is wrapped in a randomly bounded
   untrusted-content block that tells the model to treat it as data.
3. **Detection.** `PromptInjectionDetector` scores content with explainable
   heuristics. Thresholds are strictest for `EXTERNAL` and disabled for
   `SYSTEM`. A model-based classifier plugs in via `extra_signals`.
4. **Authorization.** Tool calls are authorized by the policy engine against
   the agent's identity and delegated scope, never by the model's say-so.
   This is the actual boundary: an injected instruction cannot grant
   permissions the agent does not hold.
5. **Output controls.** Secrets block the response; PII is redacted.

## Consequences

- Heuristic false negatives are expected and tolerated because layers 2, 4
  and 5 still apply.
- Heuristic false positives on `USER` content are limited by the higher
  threshold; they are tuned with the benign corpus in
  `tests/security/test_content_security.py`.
