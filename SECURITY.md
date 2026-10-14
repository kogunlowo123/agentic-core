# Security Policy

## Supported versions

Security fixes are released for the latest minor version.

## Reporting a vulnerability

Do not open a public issue. Use GitHub private vulnerability reporting
(Security tab, "Report a vulnerability"). Include affected version, a
description of the issue, reproduction steps and impact.

Expected handling:

| Stage | Target |
|---|---|
| Acknowledgement | 3 business days |
| Triage and severity (CVSS v4) | 10 business days |
| Fix for critical/high | 30 days from triage |
| Coordinated disclosure | After a fixed release is available |

## Scope

In scope: code in this repository, including the security controls in
`agentic_core.security`, `agentic_core.audit` and `agentic_core.policy`.

The heuristic prompt-injection detector is a defence-in-depth layer, not a
complete defence. Bypasses of the heuristic alone are tracked as hardening
work rather than vulnerabilities unless they also defeat trust isolation or
policy enforcement in a documented integration.
