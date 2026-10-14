"""Identifier value objects.

Agent identities follow the SPIFFE ID format so they can be issued by SPIRE
or any workload identity provider that emits SPIFFE-compatible SVIDs:

    spiffe://<trust-domain>/agent/<namespace>/<name>
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict

_TRUST_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9.\-_]{0,253}[a-z0-9])?$")
_SEGMENT = re.compile(r"^[a-z0-9]([a-z0-9\-_.]{0,62}[a-z0-9])?$")


def new_id() -> str:
    """Return a random, URL-safe identifier."""
    return uuid.uuid4().hex


def _validate_segment(value: str) -> str:
    if not _SEGMENT.fullmatch(value):
        raise ValueError(f"invalid identifier segment: {value!r}")
    return value


Segment = Annotated[str, AfterValidator(_validate_segment)]


class AgentId(BaseModel):
    """SPIFFE-formatted agent identity."""

    model_config = ConfigDict(frozen=True)

    trust_domain: str
    namespace: Segment
    name: Segment

    def model_post_init(self, _context: object) -> None:
        if not _TRUST_DOMAIN.fullmatch(self.trust_domain):
            raise ValueError(f"invalid trust domain: {self.trust_domain!r}")

    @property
    def uri(self) -> str:
        return f"spiffe://{self.trust_domain}/agent/{self.namespace}/{self.name}"

    @classmethod
    def parse(cls, uri: str) -> Self:
        prefix = "spiffe://"
        if not uri.startswith(prefix):
            raise ValueError("agent id must use the spiffe:// scheme")
        parts = uri[len(prefix) :].split("/")
        if len(parts) != 4 or parts[1] != "agent":
            raise ValueError("agent id must be spiffe://<domain>/agent/<namespace>/<name>")
        return cls(trust_domain=parts[0], namespace=parts[2], name=parts[3])

    def __str__(self) -> str:
        return self.uri
