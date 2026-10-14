"""PII and PHI identifier detection.

Pattern-based detection is a first line of defence that runs on every
request with no network call. It is tuned for precision on structured
identifiers (SSN, card numbers with Luhn, email, phone, MRN, DOB). Free-text
names and addresses need an NER service; plug one in through ``extra``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from agentic_core.security.patterns import Finding, redact

ExtraDetector = Callable[[str], Iterable[Finding]]

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)")
_SSN = re.compile(r"(?<!\d)(\d{3})-(\d{2})-(\d{4})(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")
_IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_MRN = re.compile(r"\b(?:MRN|Medical Record(?: Number)?)[\s#:]*([A-Z0-9\-]{5,15})\b", re.I)
_DOB = re.compile(
    r"\b(?:DOB|Date of Birth)[\s:]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}-\d{2}-\d{2})\b", re.I
)


def luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _ssn_valid(match: re.Match[str]) -> bool:
    area, group, serial = match.group(1), match.group(2), match.group(3)
    return not (area in {"000", "666"} or area.startswith("9") or group == "00" or serial == "0000")


class PiiDetector:
    def __init__(self, extra: Iterable[ExtraDetector] = ()) -> None:
        self._extra = list(extra)

    def detect(self, text: str) -> list[Finding]:
        findings: list[Finding] = []

        def add(kind: str, match: re.Match[str], group: int = 0) -> None:
            findings.append(
                Finding(category="pii", kind=kind, start=match.start(group), end=match.end(group))
            )

        for m in _EMAIL.finditer(text):
            add("email", m)
        for m in _SSN.finditer(text):
            if _ssn_valid(m):
                add("ssn", m)
        for m in _CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and luhn_valid(digits):
                add("payment_card", m)
        for m in _PHONE.finditer(text):
            add("phone", m)
        for m in _IPV4.finditer(text):
            add("ip_address", m)
        for m in _MRN.finditer(text):
            add("medical_record_number", m, 1)
        for m in _DOB.finditer(text):
            add("date_of_birth", m, 1)
        for detector in self._extra:
            findings.extend(detector(text))
        return findings

    def redact(self, text: str) -> tuple[str, list[Finding]]:
        findings = self.detect(text)
        return redact(text, findings), findings
