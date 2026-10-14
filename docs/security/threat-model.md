# Threat model: agentic-core

Scope: the library's controls as embedded in a host service. Host-service
threats (network exposure, authentication of callers, container escape) are
covered in each service repository's threat model.

## Assets

| Asset | Sensitivity |
|---|---|
| Prompts and retrieved context | Up to RESTRICTED (PHI, PII, GxP records) |
| Model responses | Up to RESTRICTED |
| Provider credentials | Secret |
| Audit signing keys | Secret, integrity-critical |
| Audit trail | Integrity-critical, regulated retention |
| Policy sets | Integrity-critical |

## Trust boundaries

1. Host service to model provider (network, third party).
2. Untrusted content (documents, web, tool output) to model context.
3. Host process to audit storage.
4. GitOps repository to runtime configuration (policies, provider profiles).

## STRIDE

| ID | Threat | Category | Control | Residual risk |
|---|---|---|---|---|
| T1 | Injected text in a retrieved document instructs the agent to call a tool | Elevation of privilege | Trust labels, isolation, detection (ADR-0005); tool calls authorized by policy against agent identity | Model may still produce misleading text; output review remains a host responsibility |
| T2 | Restricted data sent to an unapproved provider during failover | Information disclosure | Classification gate before routing (ADR-0003), property-tested | Misconfigured `max_classification`; mitigated by GitOps review |
| T3 | Credential leaks via config file or logs | Information disclosure | Env-var references only, `extra="forbid"`, log key scrubbing, provider error messages truncated and not echoing bodies | Host code logging raw request objects |
| T4 | Model output contains secrets or PII | Information disclosure | `inspect_output` blocks secrets, redacts PII | Free-text identifiers (names, addresses) need an NER plug-in |
| T5 | Audit events altered, deleted or reordered | Tampering, repudiation | SHA-256 chain + Ed25519 signatures, verifier (ADR-0004) | Compromise of signing key; mitigated by KMS/HSM and key rotation |
| T6 | Policy file modified to widen access | Tampering | Policy digest on every decision; host loads policies from signed GitOps source | Host must verify policy source signature |
| T7 | Regex denial of service on adversarial input | Denial of service | Bounded quantifiers; performance tests with adversarial inputs | New patterns must be added with adversarial tests |
| T8 | Provider outage exhausts retries and blocks callers | Denial of service | Circuit breakers, bounded retries, failover | All approved providers down: hard failure by design |
| T9 | Spoofed provider endpoint (DNS or proxy) | Spoofing | TLS via httpx with system trust store; base URLs are reviewed config | Corporate TLS interception requires trusted CA management |
| T10 | Hidden Unicode instructions | Tampering | Tag-character and format-control detection | Homoglyph attacks not covered by heuristics |

## OWASP Top 10 for LLM Applications (2025)

| Risk | Coverage in this library |
|---|---|
| LLM01 Prompt injection | Trust labels, isolation, heuristic detection, pluggable classifier |
| LLM02 Sensitive information disclosure | Classification gate, PII and secret redaction on input and output |
| LLM03 Supply chain | Minimal dependencies (ADR-0002), SBOM, Grype, Trivy, build provenance |
| LLM04 Data and model poisoning | Provenance records with digests and trust levels for retrieved content |
| LLM05 Improper output handling | Output guard; typed `ModelResponse`; hosts must not execute output |
| LLM06 Excessive agency | Policy engine with default deny and approval outcomes |
| LLM07 System prompt leakage | Detection of exfiltration phrasing; secrets never placed in prompts |
| LLM08 Vector and embedding weaknesses | Out of scope here; covered by the GraphRAG platform repository |
| LLM09 Misinformation | Out of scope; evaluation lives in the routing and evaluation repository |
| LLM10 Unbounded consumption | `max_tokens` bounds, cost metrics, bounded retries |

## MITRE ATLAS techniques considered

AML.T0051 LLM Prompt Injection (direct and indirect), AML.T0054 LLM
Jailbreak, AML.T0057 LLM Data Leakage, AML.T0024 Exfiltration via ML
Inference API, AML.T0010 ML Supply Chain Compromise.

## OWASP API Security Top 10 (2023)

This library exposes no network API. API risks (BOLA, broken
authentication, unrestricted resource consumption) are assessed in each
service repository.

## Risk register

| ID | Risk | Likelihood | Impact | Owner | Treatment |
|---|---|---|---|---|---|
| R1 | Novel injection bypasses heuristics | High | Medium | AI Security | Accept with layered controls; add classifier signal per deployment |
| R2 | Misconfigured provider classification | Low | High | Platform | GitOps review, CODEOWNERS on config, deployment-time validation |
| R3 | Audit signing key compromise | Low | High | Security Ops | KMS/HSM, rotation, key_id per event |
| R4 | Vendor API wire format change | Medium | Medium | Platform | Contract tests per service; adapter versioning |
