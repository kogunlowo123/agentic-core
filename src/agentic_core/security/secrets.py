"""Credential and key material detection."""

from __future__ import annotations

import math
import re
from collections import Counter

from agentic_core.security.patterns import Finding, redact

_KEY_LABEL = r"(?:RSA |EC |DSA |OPENSSH |ENCRYPTED |PGP )?PRIVATE KEY(?: BLOCK)?"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    (
        "private_key",
        re.compile(rf"-----BEGIN {_KEY_LABEL}-----[\s\S]*?-----END {_KEY_LABEL}-----"),
    ),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_\w{60,255})\b")),
    ("slack_token", re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,250}\b")),
    ("anthropic_api_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_\-]{32,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("azure_storage_key", re.compile(r"AccountKey=[A-Za-z0-9+/=]{60,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
)

_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|secret|token|passw(?:or)?d|client[_-]?secret|access[_-]?key)"
    r"\s*[:=]\s*['\"]?([^\s'\",;]{16,256})['\"]?"
)


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


class SecretScanner:
    def __init__(self, entropy_threshold: float = 3.5) -> None:
        self._entropy_threshold = entropy_threshold

    def detect(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for kind, pattern in _PATTERNS:
            findings.extend(
                Finding(category="secret", kind=kind, start=m.start(), end=m.end())
                for m in pattern.finditer(text)
            )
        for m in _ASSIGNMENT.finditer(text):
            if shannon_entropy(m.group(1)) >= self._entropy_threshold:
                findings.append(
                    Finding(
                        category="secret", kind="generic_secret", start=m.start(1), end=m.end(1)
                    )
                )
        return findings

    def redact(self, text: str) -> tuple[str, list[Finding]]:
        findings = self.detect(text)
        return redact(text, findings), findings
