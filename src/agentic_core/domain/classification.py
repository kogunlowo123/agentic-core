"""Risk, trust and data classification vocabularies used across the platform."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class RiskLevel(IntEnum):
    """Action risk tier. Ordered so policies can compare with ``>=``."""

    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


class TrustLevel(IntEnum):
    """Trust assigned to a piece of content based on its origin.

    SYSTEM content is authored by the platform operator. VERIFIED content
    comes from an authenticated, integrity-checked source. USER content is
    supplied by an authenticated principal. EXTERNAL content (web pages,
    retrieved documents, tool output) is never trusted to carry instructions.
    """

    EXTERNAL = 0
    USER = 1
    VERIFIED = 2
    SYSTEM = 3


class DataClassification(IntEnum):
    """Sensitivity label. Ordered from least to most restricted."""

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3  # PHI, PII, GxP records, secrets


class Decision(StrEnum):
    """Outcome of a policy or security evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
