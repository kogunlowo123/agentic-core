Twelve agent services, one question from every reviewer: is the guardrail in this service the same guardrail as in that one?

When each team writes its own model client, redaction filter and audit log, the honest answer is usually no. Controls drift, and drift is where audits fail.

Problem: agent platforms need identical controls for model access, policy, evidence and content security in every service. In regulated work, "mostly the same" fails.

Why it matters: a PHI redaction bug fixed in one service but not another is still a breach. Failover that sends restricted data to an unapproved provider breaks a contract.

The architecture:
Request → Content guard → Policy decision → Classification-gated router → Provider adapter → Output guard → Signed audit → Telemetry

Implementation:
1. One provider-neutral contract with thin adapters for Claude, GPT and Phi (Chat Completions), Gemini, and Bedrock (Nova, Llama).
2. The router drops every provider not approved for the request's data classification before ordering, retries or failover. Fault-injection tests check this property over random outage scripts.
3. Circuit breakers, jittered backoff, and cost or latency-aware ordering.
4. An ABAC policy engine with default deny, approval outcomes and a policy digest stamped on every decision.
5. Audit events hash-chained and Ed25519-signed, with an offline verifier.
6. Untrusted content labelled and isolated; injection heuristics, PII and secret detection on input and output.
7. OpenTelemetry GenAI metrics for tokens, cost, latency and attempts.

Best practices: injection detection is a layer, authorization is the boundary; reference credentials by name, never value; test controls adversarially.

Tradeoffs: a shared library means coordinated upgrades across services. Thin adapters keep the dependency surface small but need work when vendors add features. Heuristics miss novel attacks, so they are never the only control.

Value: one place to fix, test and evidence each control, and a smaller supply chain to scan.

As agent estates grow, the shared kernel matters more than any single agent.

Question for the community: should model routing policy live in application code at all, or belong to a central platform team?

Code: github.com/kogunlowo123/agentic-core

#AI #ArtificialIntelligence #GenerativeAI #AgenticAI #LLMOps #EnterpriseAI #AISecurity #RAG #MachineLearning #DataScience #CloudComputing #Kubernetes #MLOps #DigitalTransformation #Innovation #AIGovernance
