"""Heuristic prompt-injection detection.

This is a deterministic, explainable pre-filter. It catches common direct
and indirect injection phrasings, role-delimiter smuggling and invisible
characters. It is one layer of defence: content trust isolation, tool
allow-lists and output validation do the heavy lifting, and a classifier
model can be added through ``extra_signals``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict

from agentic_core.security.patterns import Finding

ExtraSignal = Callable[[str], Iterable[Finding]]

_SIGNALS: tuple[tuple[str, float, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        0.6,
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}"
            r"\b(?:previous|prior|above|earlier|all|your|system)\b[^.\n]{0,30}"
            r"\b(?:instructions?|prompts?|rules?|directives?|guidelines?|context)\b",
            re.I,
        ),
    ),
    (
        "role_reassignment",
        0.4,
        re.compile(
            r"\b(?:you are now|from now on,? you|act as|pretend (?:to be|you are)|"
            r"roleplay as)\b",
            re.I,
        ),
    ),
    (
        "system_prompt_exfiltration",
        0.5,
        re.compile(
            r"\b(?:reveal|print|show|repeat|output|leak|tell me)\b[^.\n]{0,30}"
            r"\b(?:system prompt|hidden (?:prompt|instructions)|initial instructions|"
            r"developer message)\b",
            re.I,
        ),
    ),
    (
        "mode_switch",
        0.5,
        re.compile(r"\b(?:developer mode|DAN mode|jailbreak|god mode|unrestricted mode)\b", re.I),
    ),
    (
        "delimiter_smuggling",
        0.6,
        re.compile(
            r"<\|(?:im_start|im_end|system|endoftext)\|>|\[/?INST\]|<<SYS>>|"
            r"^\s*#{2,}\s*(?:system|assistant)\s*:?\s*$|</?(?:system|tool_result)>",
            re.I | re.M,
        ),
    ),
    (
        "tool_coercion",
        0.4,
        re.compile(
            r"\b(?:call|invoke|run|execute|use)\b[^.\n]{0,20}\b(?:the )?tool\b[^.\n]{0,40}"
            r"\b(?:without|do not|don't)\b[^.\n]{0,20}"
            r"\b(?:ask|confirm|tell|approv|notify|check)\w*",
            re.I,
        ),
    ),
    (
        "exfiltration_url",
        0.5,
        re.compile(r"!\[[^\]]*\]\(https?://[^)]*[?&][^)]*=\s*[{$]", re.I),
    ),
)

# Unicode "tag" characters and bidi/zero-width controls used to hide text.
_INVISIBLE_CATEGORIES = {"Cf"}
_TAG_RANGE = range(0xE0000, 0xE0080)


class InjectionAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float
    findings: tuple[Finding, ...]

    @property
    def kinds(self) -> list[str]:
        return sorted({f.kind for f in self.findings})


class PromptInjectionDetector:
    def __init__(self, extra_signals: Iterable[ExtraSignal] = ()) -> None:
        self._extra = list(extra_signals)

    def assess(self, text: str) -> InjectionAssessment:
        findings: list[Finding] = []
        for kind, weight, pattern in _SIGNALS:
            findings.extend(
                Finding(
                    category="injection", kind=kind, start=m.start(), end=m.end(), weight=weight
                )
                for m in pattern.finditer(text)
            )
        hidden = [
            i
            for i, ch in enumerate(text)
            if ord(ch) in _TAG_RANGE or unicodedata.category(ch) in _INVISIBLE_CATEGORIES
        ]
        if len(hidden) >= 3:
            findings.append(
                Finding(
                    category="injection",
                    kind="hidden_characters",
                    start=hidden[0],
                    end=hidden[-1] + 1,
                    weight=0.5,
                )
            )
        for signal in self._extra:
            findings.extend(signal(text))

        # Combine as independent evidence: 1 - prod(1 - w), counting each kind once.
        best: dict[str, float] = {}
        for f in findings:
            best[f.kind] = max(best.get(f.kind, 0.0), f.weight)
        remaining = 1.0
        for weight in best.values():
            remaining *= 1.0 - min(max(weight, 0.0), 1.0)
        return InjectionAssessment(score=round(1.0 - remaining, 4), findings=tuple(findings))
