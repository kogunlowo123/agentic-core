"""Shared finding type and redaction helper."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict


class Finding(BaseModel):
    """A detected span. Never stores the matched value itself."""

    model_config = ConfigDict(frozen=True)

    category: str  # pii, secret, injection
    kind: str  # email, aws_access_key, override_instructions, ...
    start: int
    end: int
    weight: float = 1.0


def redact(text: str, findings: Iterable[Finding]) -> str:
    """Replace each finding span with ``[REDACTED:<kind>]``; overlapping spans merge."""
    spans = sorted(findings, key=lambda f: (f.start, -f.end))
    out: list[str] = []
    cursor = 0
    for finding in spans:
        if finding.end <= cursor:
            continue
        start = max(finding.start, cursor)
        out.append(text[cursor:start])
        out.append(f"[REDACTED:{finding.kind}]")
        cursor = finding.end
    out.append(text[cursor:])
    return "".join(out)
