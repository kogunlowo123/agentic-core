from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_core.domain.classification import DataClassification, Decision, RiskLevel
from agentic_core.domain.errors import PolicyDeniedError
from agentic_core.policy import (
    Condition,
    Operator,
    PolicyEngine,
    PolicyRequest,
    PolicySet,
    Resource,
    Rule,
    Subject,
)

POLICY_YAML = """
name: clinical-tools
version: "2026.10.1"
rules:
  - id: allow-fhir-read-care-team
    effect: allow
    actions: ["tool:fhir.read"]
    resource_types: ["fhir:*"]
    conditions:
      - {attribute: subject.roles, operator: contains, value: care-coordinator}
      - {attribute: resource.care_team, operator: contains_any, value: ["team-a", "team-b"]}
  - id: approve-high-risk-writes
    effect: require_approval
    actions: ["tool:fhir.write"]
    conditions:
      - {attribute: risk, operator: gte, value: 3}
  - id: allow-fhir-write
    effect: allow
    actions: ["tool:fhir.write"]
  - id: deny-restricted-outside-hours
    effect: deny
    actions: ["tool:*"]
    conditions:
      - {attribute: resource.classification, operator: gte, value: 3}
      - {attribute: environment.business_hours, operator: eq, value: false}
"""


def make_request(**overrides: object) -> PolicyRequest:
    values: dict[str, object] = {
        "subject": Subject(id="spiffe://d/agent/c/a", roles=frozenset({"care-coordinator"})),
        "action": "tool:fhir.read",
        "resource": Resource(
            type="fhir:Patient",
            id="p1",
            classification=DataClassification.RESTRICTED,
            attributes={"care_team": ["team-a"]},
        ),
        "environment": {"business_hours": True},
    }
    values.update(overrides)
    return PolicyRequest.model_validate(values)


@pytest.fixture
def engine() -> PolicyEngine:
    return PolicyEngine(PolicySet.from_yaml(POLICY_YAML))


class TestEngine:
    def test_allow(self, engine: PolicyEngine) -> None:
        decision = engine.evaluate(make_request())
        assert decision.allowed
        assert decision.matched_rules == ("allow-fhir-read-care-team",)
        assert decision.policy_version == "2026.10.1"
        assert decision.policy_digest.startswith("sha256:")

    def test_default_deny(self, engine: PolicyEngine) -> None:
        decision = engine.evaluate(make_request(action="tool:billing.read"))
        assert decision.decision is Decision.DENY
        assert decision.matched_rules == ()
        assert "default deny" in decision.reason

    def test_condition_mismatch_denies(self, engine: PolicyEngine) -> None:
        req = make_request(subject=Subject(id="x", roles=frozenset({"billing"})))
        assert engine.evaluate(req).decision is Decision.DENY

    def test_deny_overrides_allow(self, engine: PolicyEngine) -> None:
        decision = engine.evaluate(make_request(environment={"business_hours": False}))
        assert decision.decision is Decision.DENY
        assert decision.matched_rules == ("deny-restricted-outside-hours",)

    def test_approval_beats_allow(self, engine: PolicyEngine) -> None:
        decision = engine.evaluate(make_request(action="tool:fhir.write", risk=RiskLevel.HIGH))
        assert decision.decision is Decision.REQUIRE_APPROVAL
        low = engine.evaluate(make_request(action="tool:fhir.write", risk=RiskLevel.LOW))
        assert low.decision is Decision.ALLOW

    def test_enforce(self, engine: PolicyEngine) -> None:
        assert engine.enforce(make_request()).allowed
        with pytest.raises(PolicyDeniedError) as info:
            engine.enforce(make_request(environment={"business_hours": False}))
        assert info.value.rule_ids == ["deny-restricted-outside-hours"]
        approval = engine.enforce(make_request(action="tool:fhir.write", risk=RiskLevel.HIGH))
        assert approval.decision is Decision.REQUIRE_APPROVAL

    def test_digest_changes_with_policy(self, engine: PolicyEngine) -> None:
        changed = PolicySet.from_yaml(POLICY_YAML.replace("2026.10.1", "2026.10.2"))
        assert changed.digest != engine.policy.digest

    def test_from_file(self, tmp_path: Path) -> None:
        path = tmp_path / "p.yaml"
        path.write_text(POLICY_YAML, encoding="utf-8")
        assert PolicySet.from_file(path).name == "clinical-tools"


class TestValidation:
    def test_duplicate_rule_ids(self) -> None:
        rule = Rule(id="r", effect=Decision.ALLOW, actions=("a",))
        with pytest.raises(ValidationError, match="duplicate"):
            PolicySet(name="n", version="1", rules=(rule, rule))

    def test_unknown_attribute_root(self) -> None:
        with pytest.raises(ValidationError, match="unknown attribute root"):
            Condition(attribute="secret.x", operator=Operator.EQ, value=1)

    def test_rule_requires_action(self) -> None:
        with pytest.raises(ValidationError):
            Rule(id="r", effect=Decision.ALLOW, actions=())


FACTS = {
    "subject": {"roles": ["a", "b"], "clearance": 3, "org": "x"},
    "resource": {"owner": "x", "tags": ["t1"]},
    "action": "tool:x",
    "risk": 2,
    "environment": {},
}


@pytest.mark.parametrize(
    ("attribute", "operator", "value", "expected"),
    [
        ("subject.org", Operator.EQ, "x", True),
        ("subject.org", Operator.NE, "x", False),
        ("subject.org", Operator.IN, ["x", "y"], True),
        ("subject.org", Operator.NOT_IN, ["x"], False),
        ("subject.roles", Operator.CONTAINS, "a", True),
        ("subject.roles", Operator.CONTAINS_ANY, ["z", "b"], True),
        ("subject.clearance", Operator.GT, 2, True),
        ("subject.clearance", Operator.GTE, 3, True),
        ("subject.clearance", Operator.LT, 3, False),
        ("subject.clearance", Operator.LTE, 3, True),
        ("subject.org", Operator.EQ_ATTR, "resource.owner", True),
        ("subject.org", Operator.EXISTS, None, True),
        ("subject.missing", Operator.EXISTS, None, False),
        ("subject.missing", Operator.EXISTS, False, True),
        ("subject.missing", Operator.EQ, "x", False),
        ("subject.org", Operator.GT, 5, False),  # str vs int -> TypeError -> False
        ("subject.org.deeper", Operator.EQ, "x", False),
    ],
)
def test_operators(attribute: str, operator: Operator, value: object, expected: bool) -> None:
    assert (
        Condition(attribute=attribute, operator=operator, value=value).evaluate(FACTS) is expected
    )
