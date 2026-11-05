"""Bounded, offline rejection checks; no redaction or raw-value reflection."""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal


class BoundaryCategory(str, Enum):
    """Safe reasons for rejecting text, without reproducing submitted values."""

    EMAIL = "email"
    GOVERNMENT_ID = "government_id"
    PHONE = "phone"
    PATIENT_NAME = "patient_name"
    INVALID_INPUT = "invalid_input"
    INPUT_TOO_LARGE = "input_too_large"


@dataclass(frozen=True)
class Finding:
    """One detected category at a controlled path; never a matched value."""

    category: BoundaryCategory
    path: Literal["text"] = "text"


@dataclass(frozen=True)
class BoundaryResult:
    """No known violation is not proof that text is anonymous or safe to ingest."""

    findings: tuple[Finding, ...] = ()

    @property
    def has_violations(self) -> bool:
        return bool(self.findings)


class BoundaryValidationError(ValueError):
    """Fixed rejection message safe to expose without submitted input."""


# Adapted from datalife-datalake-core/src/services/pii.py (MIT), blob
# 7bf63b079800d62363e58a5db5cb980c38ec25ec. Keep parity fixtures when updating.
# Bounded/possessive patterns require Python 3.11+, as does this package.
_EMAIL_RE = re.compile(
    # The bounded domain-label repetition must backtrack when a final sentence
    # period was consumed as a separator, e.g. "synthetic@example.com.".
    r"[A-Za-z0-9._%+\-]{1,64}+@(?:[A-Za-z0-9\-]{1,63}\.){1,8}[A-Za-z]{2,24}+"
)
_CPF_RE = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_PHONE_RE = re.compile(
    r"(?<![\w\-/.])"
    r"(?:"
    r"\+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)|\d{1,4})(?:[\s.\-]?(?:\(\d{1,4}\)|\d{2,6})){0,4}+"
    r"|\(\d{1,4}\)[\s.\-]?\d{2,6}(?:[\s.\-]\d{2,6}){0,3}+"
    r"|\d{3}[\s.\-]\d{3}[\s.\-]\d{4}"
    r")"
    r"(?!\d)"
    r"(?![\s.\-]?(?:mg|mcg|ug|ml|dl|kg|g|units?|iu|mmol|mol|meq|bpm|mm|cm|hr|hrs|min|sec|kcal|cal"
    r"|milligrams?|micrograms?|millilit(?:er|re)s?|grams?|liters?|litres?)\b)",
    re.IGNORECASE,
)

# An intake-specific addition to the core value patterns. These are explicit
# identity cues, not a glossary or a general-purpose personal-name recognizer.
# Bare "Name:" must begin a line or follow sentence punctuation, so a phrase
# such as "symptom name: headache" does not trigger the rule.
_EXPLICIT_NAME_RE = re.compile(
    r"\bmy\s+(?:full\s+)?name\s+is\b"
    r"|\b(?:patient|full)\s+name\s*[:=]"
    r"|(?:^|[.!?;])[ \t]*name[ \t]*[:=]",
    re.IGNORECASE | re.MULTILINE,
)


class PIIBoundaryChecker:
    """Reject recognizable identifiers without changing or retaining the report.

    The local text limit is configurable and is not the core ingestion-body limit.
    Only this small, documented rule set is supported. No names are accepted as
    configuration: patient identity and identity mappings must remain client-side.
    """

    def __init__(self, *, max_text_bytes: int = 16_384) -> None:
        if type(max_text_bytes) is not int or max_text_bytes < 1:
            raise ValueError("max_text_bytes must be a positive integer")
        self.max_text_bytes = max_text_bytes

    def check_text(self, text: str) -> BoundaryResult:
        """Return safe categories, once per kind, in a deterministic order."""
        if not isinstance(text, str):
            return BoundaryResult((Finding(BoundaryCategory.INVALID_INPUT),))
        # A quick character bound prevents encoding arbitrarily large input first.
        if len(text) > self.max_text_bytes:
            return BoundaryResult((Finding(BoundaryCategory.INPUT_TOO_LARGE),))
        try:
            size = len(text.encode("utf-8"))
        except UnicodeEncodeError:
            return BoundaryResult((Finding(BoundaryCategory.INVALID_INPUT),))
        if size > self.max_text_bytes:
            return BoundaryResult((Finding(BoundaryCategory.INPUT_TOO_LARGE),))
        if not text.strip():
            return BoundaryResult((Finding(BoundaryCategory.INVALID_INPUT),))

        categories = []
        if _EMAIL_RE.search(text):
            categories.append(BoundaryCategory.EMAIL)
        if _CPF_RE.search(text) or _SSN_RE.search(text):
            categories.append(BoundaryCategory.GOVERNMENT_ID)
        if any(
            sum(char.isdigit() for char in match.group()) >= 7
            for match in _PHONE_RE.finditer(text)
        ):
            categories.append(BoundaryCategory.PHONE)
        if _EXPLICIT_NAME_RE.search(text):
            categories.append(BoundaryCategory.PATIENT_NAME)
        return BoundaryResult(tuple(Finding(category) for category in categories))

    def require_text(self, text: str) -> None:
        """Raise on known violations; never redact, log, or include input in errors."""
        if self.check_text(text).has_violations:
            raise BoundaryValidationError("text_boundary_rejected")
