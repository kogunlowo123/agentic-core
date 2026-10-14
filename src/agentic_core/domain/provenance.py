"""Provenance records attach origin, integrity and trust metadata to content."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentic_core.domain.classification import DataClassification, TrustLevel


def canonical_json(value: Any) -> bytes:
    """Deterministic JSON encoding used for hashing and signing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def content_digest(content: str | bytes) -> str:
    """SHA-256 digest of content, prefixed with the algorithm name."""
    data = content.encode() if isinstance(content, str) else content
    return "sha256:" + hashlib.sha256(data).hexdigest()


class ProvenanceRecord(BaseModel):
    """Where a piece of content came from and how far it can be trusted."""

    model_config = ConfigDict(frozen=True)

    source_uri: str = Field(description="Canonical location of the source")
    source_type: str = Field(description="e.g. fhir, document, tool, model, user")
    digest: str = Field(description="sha256 digest of the exact content used")
    trust: TrustLevel
    classification: DataClassification
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retrieved_by: str = Field(description="Agent or service identity that fetched it")
    parent_digests: tuple[str, ...] = Field(
        default=(), description="Digests of inputs this content was derived from"
    )

    @classmethod
    def for_content(
        cls,
        content: str | bytes,
        *,
        source_uri: str,
        source_type: str,
        trust: TrustLevel,
        classification: DataClassification,
        retrieved_by: str,
        parents: tuple[str, ...] = (),
    ) -> ProvenanceRecord:
        return cls(
            source_uri=source_uri,
            source_type=source_type,
            digest=content_digest(content),
            trust=trust,
            classification=classification,
            retrieved_by=retrieved_by,
            parent_digests=parents,
        )

    def verify(self, content: str | bytes) -> bool:
        """True when ``content`` is byte-identical to what was recorded."""
        return content_digest(content) == self.digest
