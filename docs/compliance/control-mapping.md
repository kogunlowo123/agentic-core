# Control mapping

How library capabilities support controls in common frameworks. A library
alone does not make a system compliant; each service repository maps its
full control set and evidence.

| Capability | NIST AI RMF 1.0 | NIST SP 800-53 Rev. 5 | SOC 2 (TSC 2017) | ISO/IEC 27001:2022 Annex A | HIPAA Security Rule | 21 CFR Part 11 |
|---|---|---|---|---|---|---|
| Signed, hash-chained audit trail | MANAGE 4.1 | AU-2, AU-3, AU-9, AU-10 | CC7.2 | 8.15 | 164.312(b) | 11.10(e) |
| Policy engine with default deny and approval outcomes | GOVERN 1.4, MANAGE 2.4 | AC-3, AC-6 | CC6.1, CC6.3 | 5.15, 8.3 | 164.312(a)(1) | 11.10(d), 11.10(g) |
| Policy digest recorded per decision | GOVERN 1.4 | CM-3, AU-3 | CC8.1 | 8.32 | 164.312(b) | 11.10(e) |
| Classification-gated model routing | MAP 4.1, MANAGE 2.2 | AC-4, SA-9 | CC6.7, CC9.2 | 5.14, 5.19 | 164.308(b)(1), 164.312(e)(1) | n/a |
| PII/PHI detection and redaction | MEASURE 2.10 | SI-15, PT-2 | C1.1, P4.1 | 8.11 | 164.502(b), 164.514 | n/a |
| Credential detection on input and output | MANAGE 2.3 | IA-5(7), SI-4 | CC6.1 | 8.12 | 164.312(a)(1) | n/a |
| Prompt-injection detection and isolation | MEASURE 2.7 | SI-10, SI-3 | CC7.1 | 8.7 | 164.308(a)(5)(ii)(B) | n/a |
| Provenance records with content digests | MAP 2.3, MEASURE 2.8 | SI-7, AU-10 | PI1.2 | 5.33 | 164.312(c)(1) | 11.10(a) |
| Telemetry: latency, tokens, cost, attempts | MEASURE 2.4, MANAGE 4.1 | AU-6, SI-4 | CC7.2, A1.1 | 8.16 | 164.308(a)(1)(ii)(D) | n/a |
| Circuit breakers and failover | MANAGE 2.4 | CP-10, SC-5 | A1.2 | 8.14 | 164.308(a)(7) | n/a |

GxP note: validation evidence (IQ/OQ/PQ) for a computerized system is
produced by the deploying service. This repository contributes requirement
traceability through tests named after the controls they verify and a
CI run log per release tag.
