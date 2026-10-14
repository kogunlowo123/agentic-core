"""Committed configuration and policy files must stay valid and behave as documented."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentic_core.domain.classification import DataClassification, Decision, RiskLevel
from agentic_core.models.factory import (
    ProvidersConfig,
    build_providers,
    env_references,
    expand_env,
)
from agentic_core.policy import PolicyEngine, PolicyRequest, PolicySet, Resource, Subject

ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = ROOT / "configs" / "providers.yaml"
CONFIG_DOC = ROOT / "docs" / "operations" / "configuration.md"


def referenced_vars() -> set[str]:
    text = PROVIDERS.read_text(encoding="utf-8")
    return env_references(text) | set(
        re.findall(r"(?:api_key_env|access_token_env):\s*([A-Z0-9_]+)", text)
    )


def synthetic_env() -> dict[str, str]:
    env = {
        name: "1.5" if name.endswith("_PER_MTOK") else f"test-{name.lower()}"
        for name in referenced_vars()
    }
    env["AZURE_OPENAI_ENDPOINT"] = "https://test.openai.azure.com"
    env["AZURE_AI_FOUNDRY_ENDPOINT"] = "https://test.services.ai.azure.com"
    env["AWS_REGION"] = "us-east-1"
    env["GCP_REGION"] = "us-central1"
    return env


def test_providers_config_builds_with_resolved_env() -> None:
    config = ProvidersConfig.from_file(PROVIDERS, env=synthetic_env())
    names = [p.profile.name for p in config.providers]
    assert len(names) == len(set(names))
    assert config.providers[0].profile.input_cost_per_mtok == 1.5
    gemini = next(p for p in config.providers if p.profile.name == "gemini")
    assert gemini.base_url == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/"
        "test-gcp_project_id/locations/us-central1/publishers/google"
    )
    assert len(build_providers(config, env=synthetic_env())) == len(names)


def test_providers_config_fails_closed_without_env() -> None:
    with pytest.raises(ValueError, match="unset environment variables") as info:
        ProvidersConfig.from_file(PROVIDERS, env={})
    assert "AZURE_OPENAI_ENDPOINT" in str(info.value)


def test_every_variable_is_documented() -> None:
    documented = CONFIG_DOC.read_text(encoding="utf-8")
    undocumented = sorted(v for v in referenced_vars() if f"`{v}`" not in documented)
    assert undocumented == []


def test_expand_env_rejects_empty_values() -> None:
    with pytest.raises(ValueError, match="X"):
        expand_env("${X}", {"X": ""})
    assert expand_env("a ${X} b $notref", {"X": "1"}) == "a 1 b $notref"


def test_comment_references_are_ignored() -> None:
    text = "# set ${DOCUMENTED} in env\nkey: ${X}\n  # ${ALSO_IGNORED}"
    assert env_references(text) == {"X"}
    assert expand_env(text, {"X": "v"}) == "# set ${DOCUMENTED} in env\nkey: v\n  # ${ALSO_IGNORED}"


def test_no_placeholders_in_committed_files() -> None:
    pattern = re.compile(r"YOUR[-_]|REPLACE[-_ ]ME|CHANGEME|<your", re.I)
    offenders = [
        str(p.relative_to(ROOT))
        for folder in ("configs", "policies", "docs", "src")
        for p in (ROOT / folder).rglob("*")
        if p.is_file()
        and p.suffix in {".yaml", ".yml", ".md", ".py"}
        and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_baseline_policy_behaviour() -> None:
    engine = PolicyEngine(PolicySet.from_file(ROOT / "policies" / "agent-tools.yaml"))
    active = Subject(id="a", attributes={"status": "active", "scopes": ["tools:read"]})

    def decide(**kw: object) -> Decision:
        values: dict[str, object] = {
            "subject": active,
            "action": "tool:fhir.read",
            "resource": Resource(type="fhir:Patient"),
        }
        values.update(kw)
        return engine.evaluate(PolicyRequest.model_validate(values)).decision

    restricted = Resource(type="fhir:Patient", classification=DataClassification.RESTRICTED)
    assert decide() is Decision.ALLOW
    assert decide(action="tool:fhir.write") is Decision.DENY
    assert decide(risk=RiskLevel.CRITICAL) is Decision.REQUIRE_APPROVAL
    assert decide(resource=restricted) is Decision.DENY
    assert decide(resource=restricted, environment={"purpose_of_use": "TREAT"}) is Decision.ALLOW
    revoked = Subject(id="a", attributes={"status": "revoked", "scopes": ["tools:read"]})
    assert decide(subject=revoked) is Decision.DENY
