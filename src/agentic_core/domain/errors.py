"""Error hierarchy. Every error carries a stable machine-readable code."""

from __future__ import annotations


class AgenticCoreError(Exception):
    """Base class for all agentic-core errors."""

    code: str = "agentic_core_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ProviderError(AgenticCoreError):
    """A model provider returned an error or an unparseable response."""

    code = "provider_error"

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable


class ProviderUnavailableError(AgenticCoreError):
    """No provider in the route could serve the request."""

    code = "provider_unavailable"

    def __init__(self, message: str, *, attempts: list[str]) -> None:
        super().__init__(message)
        self.attempts = attempts


class PolicyDeniedError(AgenticCoreError):
    """The policy engine denied the requested action."""

    code = "policy_denied"

    def __init__(self, message: str, *, rule_ids: list[str]) -> None:
        super().__init__(message)
        self.rule_ids = rule_ids


class SecurityViolationError(AgenticCoreError):
    """Input or output failed a security control."""

    code = "security_violation"

    def __init__(self, message: str, *, findings: list[str]) -> None:
        super().__init__(message)
        self.findings = findings


class AuditIntegrityError(AgenticCoreError):
    """The audit chain failed hash or signature verification."""

    code = "audit_integrity"

    def __init__(self, message: str, *, sequence: int) -> None:
        super().__init__(message)
        self.sequence = sequence
