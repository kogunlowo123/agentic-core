from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentic_core.audit import (
    GENESIS_HASH,
    AuditEvent,
    AuditLog,
    InMemoryAuditSink,
    JsonlAuditSink,
    verify_chain,
)
from agentic_core.domain.errors import AuditIntegrityError


@pytest.fixture
def key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


async def write_events(log: AuditLog, n: int) -> None:
    for i in range(n):
        await log.record(
            actor="spiffe://d/agent/a/b",
            action="tool:fhir.read",
            resource=f"Patient/{i}",
            outcome="allow",
            correlation_id="c1",
            details={"i": i},
        )


class TestAuditLog:
    async def test_chain_verifies(self, key: Ed25519PrivateKey) -> None:
        sink = InMemoryAuditSink()
        log = AuditLog(sink, key, key_id="k1")
        await write_events(log, 5)
        assert sink.events[0].prev_hash == GENESIS_HASH
        assert [e.sequence for e in sink.events] == [0, 1, 2, 3, 4]
        assert verify_chain(sink.events, {"k1": key.public_key()}) == 5

    async def test_concurrent_appends_stay_ordered(self, key: Ed25519PrivateKey) -> None:
        sink = InMemoryAuditSink()
        log = AuditLog(sink, key, key_id="k1")
        await asyncio.gather(
            *(log.record(actor="a", action="x", resource=str(i), outcome="ok") for i in range(50))
        )
        assert verify_chain(sink.events, {"k1": key.public_key()}) == 50

    async def test_jsonl_round_trip_and_resume(
        self, key: Ed25519PrivateKey, tmp_path: Path
    ) -> None:
        path = tmp_path / "audit" / "log.jsonl"
        await write_events(AuditLog(JsonlAuditSink(path), key, key_id="k1"), 3)
        # A new process resumes from the file tail.
        await write_events(AuditLog(JsonlAuditSink(path), key, key_id="k1"), 2)
        events = [e async for e in JsonlAuditSink(path).read()]
        assert verify_chain(events, {"k1": key.public_key()}) == 5

    async def test_empty_jsonl(self, tmp_path: Path) -> None:
        sink = JsonlAuditSink(tmp_path / "none.jsonl")
        assert [e async for e in sink.read()] == []
        assert await sink.tail() is None

    async def test_in_memory_read(self, key: Ed25519PrivateKey) -> None:
        sink = InMemoryAuditSink()
        await write_events(AuditLog(sink, key, key_id="k1"), 2)
        assert len([e async for e in sink.read()]) == 2


@pytest.mark.security
class TestTamperDetection:
    @pytest.fixture
    async def events(self, key: Ed25519PrivateKey) -> list[AuditEvent]:
        sink = InMemoryAuditSink()
        await write_events(AuditLog(sink, key, key_id="k1"), 4)
        return sink.events

    def test_altered_content(self, events: list[AuditEvent], key: Ed25519PrivateKey) -> None:
        events[2] = events[2].model_copy(update={"outcome": "deny"})
        with pytest.raises(AuditIntegrityError, match="altered") as info:
            verify_chain(events, {"k1": key.public_key()})
        assert info.value.sequence == 2

    def test_deleted_event(self, events: list[AuditEvent], key: Ed25519PrivateKey) -> None:
        del events[1]
        with pytest.raises(AuditIntegrityError, match="sequence gap"):
            verify_chain(events, {"k1": key.public_key()})

    def test_reordered(self, events: list[AuditEvent], key: Ed25519PrivateKey) -> None:
        events[1], events[2] = events[2], events[1]
        with pytest.raises(AuditIntegrityError):
            verify_chain(events, {"k1": key.public_key()})

    def test_rehashed_without_key(self, events: list[AuditEvent], key: Ed25519PrivateKey) -> None:
        # Attacker edits and recomputes the hash but cannot re-sign.
        forged = events[3].model_copy(update={"outcome": "deny"})
        events[3] = forged.model_copy(update={"hash": forged.compute_hash()})
        with pytest.raises(AuditIntegrityError, match="invalid signature"):
            verify_chain(events, {"k1": key.public_key()})

    def test_broken_link(self, events: list[AuditEvent], key: Ed25519PrivateKey) -> None:
        events[2] = events[2].model_copy(update={"prev_hash": "f" * 64})
        with pytest.raises(AuditIntegrityError, match="broken hash link"):
            verify_chain(events, {"k1": key.public_key()})

    def test_wrong_key(self, events: list[AuditEvent]) -> None:
        other = Ed25519PrivateKey.generate().public_key()
        with pytest.raises(AuditIntegrityError, match="invalid signature"):
            verify_chain(events, {"k1": other})

    def test_unknown_key(self, events: list[AuditEvent], key: Ed25519PrivateKey) -> None:
        with pytest.raises(AuditIntegrityError, match="unknown key"):
            verify_chain(events, {"k2": key.public_key()})
