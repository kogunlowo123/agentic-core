from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_core.domain.classification import DataClassification, RiskLevel, TrustLevel
from agentic_core.domain.errors import (
    AgenticCoreError,
    PolicyDeniedError,
    ProviderError,
    ProviderUnavailableError,
)
from agentic_core.domain.identifiers import AgentId, new_id
from agentic_core.domain.provenance import ProvenanceRecord, canonical_json, content_digest
from agentic_core.models.types import Message, ModelRequest, Role, TokenUsage


class TestAgentId:
    def test_round_trip(self) -> None:
        agent = AgentId(trust_domain="corp.example", namespace="clinical", name="care-coord")
        assert agent.uri == "spiffe://corp.example/agent/clinical/care-coord"
        assert AgentId.parse(agent.uri) == agent
        assert str(agent) == agent.uri

    @pytest.mark.parametrize(
        "uri",
        [
            "https://corp.example/agent/a/b",
            "spiffe://corp.example/workload/a/b",
            "spiffe://corp.example/agent/a",
            "spiffe://corp.example/agent/A/b",
            "spiffe://corp.example/agent/a/b/c",
        ],
    )
    def test_rejects_malformed(self, uri: str) -> None:
        with pytest.raises(ValueError, match=r"agent id|identifier segment"):
            AgentId.parse(uri)

    def test_rejects_bad_trust_domain(self) -> None:
        with pytest.raises(ValueError, match="trust domain"):
            AgentId(trust_domain="Bad Domain", namespace="a", name="b")

    def test_new_id_unique(self) -> None:
        assert len({new_id() for _ in range(100)}) == 100


class TestProvenance:
    def test_digest_is_stable_and_verifies(self) -> None:
        record = ProvenanceRecord.for_content(
            "result",
            source_uri="fhir://Observation/1",
            source_type="fhir",
            trust=TrustLevel.VERIFIED,
            classification=DataClassification.RESTRICTED,
            retrieved_by="spiffe://d/agent/a/b",
            parents=("sha256:abc",),
        )
        assert record.digest == content_digest(b"result")
        assert record.verify("result")
        assert not record.verify("result ")
        assert record.parent_digests == ("sha256:abc",)

    def test_canonical_json_sorts_keys(self) -> None:
        assert canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


class TestOrdering:
    def test_levels_are_ordered(self) -> None:
        assert RiskLevel.CRITICAL > RiskLevel.LOW
        assert TrustLevel.SYSTEM > TrustLevel.EXTERNAL
        assert DataClassification.RESTRICTED > DataClassification.PUBLIC


class TestErrors:
    def test_codes(self) -> None:
        assert AgenticCoreError("x", code="custom").code == "custom"
        assert AgenticCoreError("x").code == "agentic_core_error"
        err = ProviderError("x", provider="p", status_code=429, retryable=True)
        assert (err.code, err.provider, err.status_code, err.retryable) == (
            "provider_error",
            "p",
            429,
            True,
        )
        assert ProviderUnavailableError("x", attempts=["a"]).attempts == ["a"]
        assert PolicyDeniedError("x", rule_ids=["r"]).rule_ids == ["r"]


class TestModelRequest:
    def test_system_split(self) -> None:
        req = ModelRequest(
            messages=(
                Message(role=Role.SYSTEM, content="a"),
                Message(role=Role.SYSTEM, content="b"),
                Message(role=Role.USER, content="q"),
            )
        )
        assert req.system_prompt == "a\n\nb"
        assert [m.content for m in req.conversation] == ["q"]

    def test_requires_non_system_message(self) -> None:
        with pytest.raises(ValidationError, match="at least one user"):
            ModelRequest(messages=(Message(role=Role.SYSTEM, content="a"),))

    def test_no_system(self) -> None:
        req = ModelRequest(messages=(Message(role=Role.USER, content="q"),))
        assert req.system_prompt is None

    def test_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ModelRequest(messages=(Message(role=Role.USER, content="q"),), max_tokens=0)

    def test_usage_total(self) -> None:
        assert TokenUsage(input_tokens=3, output_tokens=4).total_tokens == 7
