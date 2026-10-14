"""Hash-chained, Ed25519-signed audit events.

Each event stores the hash of its predecessor. Altering, deleting, inserting
or reordering any event breaks every later hash, and each event hash is
signed so an attacker with write access to storage but not to the signing
key cannot re-forge the chain. Signing keys belong in a KMS/HSM; this module
accepts any object exposing ``sign`` so a KMS-backed signer can be supplied.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from agentic_core.domain.errors import AuditIntegrityError
from agentic_core.domain.identifiers import new_id
from agentic_core.domain.provenance import canonical_json

GENESIS_HASH = "0" * 64


class Signer(Protocol):
    def sign(self, data: bytes) -> bytes: ...


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=new_id)
    sequence: int = Field(ge=0)
    timestamp: datetime
    actor: str
    action: str
    resource: str
    outcome: str
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str = ""
    signature: str = ""
    key_id: str = ""

    def body(self) -> dict[str, Any]:
        """Fields covered by the hash (everything except hash and signature)."""
        return self.model_dump(mode="json", exclude={"hash", "signature"})

    def compute_hash(self) -> str:
        return hashlib.sha256(canonical_json(self.body())).hexdigest()


class AuditSink(Protocol):
    async def append(self, event: AuditEvent) -> None: ...

    def read(self) -> AsyncIterator[AuditEvent]: ...

    async def tail(self) -> AuditEvent | None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    async def read(self) -> AsyncIterator[AuditEvent]:
        for event in list(self.events):
            yield event

    async def tail(self) -> AuditEvent | None:
        return self.events[-1] if self.events else None


class JsonlAuditSink:
    """Append-only JSON Lines file. Pair with WORM storage in production."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, event: AuditEvent) -> None:
        line = event.model_dump_json() + "\n"
        await asyncio.to_thread(self._write, line)

    def _write(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()

    async def read(self) -> AsyncIterator[AuditEvent]:
        if not self._path.exists():
            return
        lines = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
        for line in lines.splitlines():
            if line.strip():
                yield AuditEvent.model_validate_json(line)

    async def tail(self) -> AuditEvent | None:
        last: AuditEvent | None = None
        async for event in self.read():
            last = event
        return last


class AuditLog:
    """Serializes appends so sequence numbers and hashes stay consistent."""

    def __init__(self, sink: AuditSink, signer: Signer, *, key_id: str) -> None:
        self._sink = sink
        self._signer = signer
        self._key_id = key_id
        self._lock = asyncio.Lock()
        self._head: AuditEvent | None = None
        self._loaded = False

    async def record(
        self,
        *,
        actor: str,
        action: str,
        resource: str,
        outcome: str,
        correlation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEvent:
        async with self._lock:
            if not self._loaded:
                self._head = await self._sink.tail()
                self._loaded = True
            draft = AuditEvent(
                sequence=0 if self._head is None else self._head.sequence + 1,
                timestamp=datetime.now(UTC),
                actor=actor,
                action=action,
                resource=resource,
                outcome=outcome,
                correlation_id=correlation_id,
                details=details or {},
                prev_hash=GENESIS_HASH if self._head is None else self._head.hash,
                key_id=self._key_id,
            )
            digest = draft.compute_hash()
            signature = base64.b64encode(self._signer.sign(bytes.fromhex(digest))).decode()
            event = draft.model_copy(update={"hash": digest, "signature": signature})
            await self._sink.append(event)
            self._head = event
            return event


def verify_chain(events: Iterable[AuditEvent], public_keys: dict[str, Ed25519PublicKey]) -> int:
    """Verify ordering, hash linkage and signatures. Returns events verified."""
    expected_prev = GENESIS_HASH
    count = 0
    for expected_seq, event in enumerate(events):
        if event.sequence != expected_seq:
            raise AuditIntegrityError(
                f"sequence gap: expected {expected_seq}, got {event.sequence}",
                sequence=event.sequence,
            )
        if event.prev_hash != expected_prev:
            raise AuditIntegrityError("broken hash link", sequence=event.sequence)
        if event.compute_hash() != event.hash:
            raise AuditIntegrityError("event content altered", sequence=event.sequence)
        key = public_keys.get(event.key_id)
        if key is None:
            raise AuditIntegrityError(f"unknown key id {event.key_id!r}", sequence=event.sequence)
        try:
            key.verify(base64.b64decode(event.signature), bytes.fromhex(event.hash))
        except (InvalidSignature, ValueError) as exc:
            raise AuditIntegrityError("invalid signature", sequence=event.sequence) from exc
        expected_prev = event.hash
        count += 1
    return count
