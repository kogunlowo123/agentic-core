"""ABAC policy evaluation.

Combining algorithm, in order:

1. Any matching DENY rule denies.
2. Otherwise any matching REQUIRE_APPROVAL rule requires human approval.
3. Otherwise any matching ALLOW rule allows.
4. Otherwise the request is denied (default deny).

Rules are plain data so they can be stored in Git, reviewed, signed and
versioned. The policy set digest is recorded with every decision so an
auditor can prove which policy produced which outcome.
"""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentic_core.domain.classification import DataClassification, Decision, RiskLevel
from agentic_core.domain.errors import PolicyDeniedError
from agentic_core.domain.provenance import canonical_json, content_digest


class Operator(StrEnum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    CONTAINS_ANY = "contains_any"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EXISTS = "exists"
    EQ_ATTR = "eq_attr"  # compare two attributes, value is the other path


_MISSING = object()


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    attribute: str = Field(description="Dotted path, e.g. subject.roles or resource.owner")
    operator: Operator
    value: Any = None

    @field_validator("attribute")
    @classmethod
    def _root(cls, value: str) -> str:
        if value.split(".", 1)[0] not in {"subject", "resource", "action", "environment", "risk"}:
            raise ValueError(f"unknown attribute root in {value!r}")
        return value

    def evaluate(self, facts: dict[str, Any]) -> bool:
        actual = _resolve(facts, self.attribute)
        op = self.operator
        if op is Operator.EXISTS:
            return (actual is not _MISSING) == bool(self.value if self.value is not None else True)
        if actual is _MISSING:
            return False
        expected = _resolve(facts, str(self.value)) if op is Operator.EQ_ATTR else self.value
        try:
            return _compare(op, actual, expected)
        except TypeError:
            return False


def _compare(op: Operator, actual: Any, expected: Any) -> bool:  # noqa: PLR0911
    match op:
        case Operator.EQ | Operator.EQ_ATTR:
            return bool(actual == expected)
        case Operator.NE:
            return bool(actual != expected)
        case Operator.IN:
            return actual in expected
        case Operator.NOT_IN:
            return actual not in expected
        case Operator.CONTAINS:
            return expected in actual
        case Operator.CONTAINS_ANY:
            return any(item in actual for item in expected)
        case Operator.GT:
            return bool(actual > expected)
        case Operator.GTE:
            return bool(actual >= expected)
        case Operator.LT:
            return bool(actual < expected)
        case Operator.LTE:
            return bool(actual <= expected)
    return False  # pragma: no cover - exhaustive match


def _resolve(facts: dict[str, Any], path: str) -> Any:
    current: Any = facts
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    description: str = ""
    effect: Decision
    actions: tuple[str, ...] = Field(min_length=1, description="Glob patterns, e.g. tool:fhir.*")
    resource_types: tuple[str, ...] = ("*",)
    conditions: tuple[Condition, ...] = ()

    def matches(self, request: PolicyRequest, facts: dict[str, Any]) -> bool:
        if not any(fnmatch.fnmatchcase(request.action, a) for a in self.actions):
            return False
        if not any(fnmatch.fnmatchcase(request.resource.type, t) for t in self.resource_types):
            return False
        return all(c.evaluate(facts) for c in self.conditions)


class PolicySet(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    rules: tuple[Rule, ...]

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
        ids = [r.id for r in rules]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate rule ids: {sorted(duplicates)}")
        return rules

    @property
    def digest(self) -> str:
        return content_digest(canonical_json(self.model_dump(mode="json")))

    @classmethod
    def from_yaml(cls, text: str) -> PolicySet:
        return cls.model_validate(yaml.safe_load(text))

    @classmethod
    def from_file(cls, path: Path) -> PolicySet:
        return cls.from_yaml(path.read_text(encoding="utf-8"))


class Subject(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str = Field(default="agent", description="agent, user, service")
    roles: frozenset[str] = frozenset()
    attributes: dict[str, Any] = Field(default_factory=dict)


class Resource(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    id: str = "*"
    classification: DataClassification = DataClassification.INTERNAL
    attributes: dict[str, Any] = Field(default_factory=dict)


class PolicyRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject: Subject
    action: str
    resource: Resource
    risk: RiskLevel = RiskLevel.LOW
    environment: dict[str, Any] = Field(default_factory=dict)

    def facts(self) -> dict[str, Any]:
        subject = {
            "id": self.subject.id,
            "kind": self.subject.kind,
            "roles": sorted(self.subject.roles),
            **self.subject.attributes,
        }
        resource = {
            "type": self.resource.type,
            "id": self.resource.id,
            "classification": int(self.resource.classification),
            **self.resource.attributes,
        }
        return {
            "subject": subject,
            "resource": resource,
            "action": self.action,
            "risk": int(self.risk),
            "environment": dict(self.environment),
        }


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Decision
    matched_rules: tuple[str, ...]
    policy_name: str
    policy_version: str
    policy_digest: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW


class PolicyEngine:
    def __init__(self, policy: PolicySet) -> None:
        self._policy = policy
        self._digest = policy.digest

    @property
    def policy(self) -> PolicySet:
        return self._policy

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        facts = request.facts()
        matched = [r for r in self._policy.rules if r.matches(request, facts)]
        by_effect: dict[Decision, list[str]] = {d: [] for d in Decision}
        for rule in matched:
            by_effect[rule.effect].append(rule.id)

        if by_effect[Decision.DENY]:
            decision, ids, reason = Decision.DENY, by_effect[Decision.DENY], "explicit deny"
        elif by_effect[Decision.REQUIRE_APPROVAL]:
            decision = Decision.REQUIRE_APPROVAL
            ids, reason = by_effect[Decision.REQUIRE_APPROVAL], "human approval required"
        elif by_effect[Decision.ALLOW]:
            decision, ids, reason = Decision.ALLOW, by_effect[Decision.ALLOW], "explicit allow"
        else:
            decision, ids, reason = Decision.DENY, [], "no matching allow rule (default deny)"

        return PolicyDecision(
            decision=decision,
            matched_rules=tuple(ids),
            policy_name=self._policy.name,
            policy_version=self._policy.version,
            policy_digest=self._digest,
            reason=reason,
        )

    def enforce(self, request: PolicyRequest) -> PolicyDecision:
        """Evaluate and raise unless the request is allowed outright."""
        decision = self.evaluate(request)
        if decision.decision is Decision.DENY:
            raise PolicyDeniedError(
                f"{request.action} on {request.resource.type}:{request.resource.id} denied: "
                f"{decision.reason}",
                rule_ids=list(decision.matched_rules),
            )
        return decision
