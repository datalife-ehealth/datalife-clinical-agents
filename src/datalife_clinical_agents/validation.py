"""Bounded, offline rejection checks; no redaction or raw-value reflection."""

import json
import re
from dataclasses import dataclass, fields
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ValidationError

from .schemas import (
    CandidateIntakeV1, IngestionEnvelopeV1, ObservationV1, SessionInputV1, SymptomValue,
)


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


@dataclass(frozen=True)
class ValidationLimits:
    """Local text cap plus the reference core's default JSON resource limits."""

    max_text_bytes: int = 16_384
    max_body_bytes: int = 1_000_000
    max_depth: int = 64
    max_nodes: int = 10_000

    def __post_init__(self) -> None:
        if any(type(getattr(self, item.name)) is not int or getattr(self, item.name) < 1
               for item in fields(self)):
            raise ValueError("validation limits must be positive integers")


DEFAULT_LIMITS = ValidationLimits()


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


def _utf8_size(text: str, maximum: int) -> int:
    """Check character length before allocating a bounded UTF-8 representation."""
    if len(text) > maximum:
        raise BoundaryValidationError("payload_too_large")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        raise BoundaryValidationError("invalid_text_encoding") from None
    if size > maximum:
        raise BoundaryValidationError("payload_too_large")
    return size


def require_structure_limits(value: object, *, limits: ValidationLimits = DEFAULT_LIMITS) -> None:
    """Bound Python inputs before schema validation and JSON values after parsing.

    Match core node/depth counting: the root is depth 1, values and containers
    count as nodes, and object keys do not. Also bound aggregate string/key bytes
    before model cloning; the exact JSON byte size is checked during serialization.
    """
    stack = [(value, 1)]
    nodes = 0
    text_bytes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > limits.max_nodes:
            raise BoundaryValidationError("payload_node_limit")
        if depth > limits.max_depth:
            raise BoundaryValidationError("payload_depth_limit")
        if isinstance(current, BaseModel):
            current = current.__dict__
        if isinstance(current, dict):
            if len(current) + nodes + len(stack) > limits.max_nodes:
                raise BoundaryValidationError("payload_node_limit")
            for key, child in current.items():
                if not isinstance(key, str):
                    raise BoundaryValidationError("unsupported_object_key")
                text_bytes += _utf8_size(key, limits.max_body_bytes)
                if text_bytes > limits.max_body_bytes:
                    raise BoundaryValidationError("payload_too_large")
                stack.append((child, depth + 1))
        elif isinstance(current, (list, tuple)):
            if len(current) + nodes + len(stack) > limits.max_nodes:
                raise BoundaryValidationError("payload_node_limit")
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str):
            text_bytes += _utf8_size(current, limits.max_body_bytes)
            if text_bytes > limits.max_body_bytes:
                raise BoundaryValidationError("payload_too_large")


def validate_session_input(
    value: object, *, limits: ValidationLimits = DEFAULT_LIMITS,
) -> SessionInputV1:
    """Validate the input contract and screen raw text before extraction or review."""
    require_structure_limits(value, limits=limits)
    try:
        session = SessionInputV1.model_validate(value)
    except ValidationError:
        raise BoundaryValidationError("invalid_session_input") from None
    require_structure_limits(session, limits=limits)
    PIIBoundaryChecker(max_text_bytes=limits.max_text_bytes).require_text(session.intake_input.raw_text)
    return session


def _require_observation_text(observation: ObservationV1, checker: PIIBoundaryChecker) -> None:
    if isinstance(observation.value_unit, SymptomValue) and observation.value_unit.symptom is not None:
        checker.require_text(observation.value_unit.symptom)
    if observation.uncertainty.abstained_reason is not None:
        checker.require_text(observation.uncertainty.abstained_reason)


def validate_observation(
    value: object, *, limits: ValidationLimits = DEFAULT_LIMITS,
) -> ObservationV1:
    """Reject unsupported extraction fields/types and identifiers in reported text."""
    require_structure_limits(value, limits=limits)
    try:
        observation = ObservationV1.model_validate(value)
    except ValidationError:
        raise BoundaryValidationError("invalid_observation") from None
    require_structure_limits(observation, limits=limits)
    _require_observation_text(observation, PIIBoundaryChecker(max_text_bytes=limits.max_text_bytes))
    return observation


def validate_candidate(
    value: object, *, session_input: SessionInputV1, limits: ValidationLimits = DEFAULT_LIMITS,
) -> CandidateIntakeV1:
    """Reuse schema invariants, bind the source session, and screen all free text.

    This checks content, not the authority to set workflow metadata or approve it.
    """
    session = validate_session_input(session_input, limits=limits)
    require_structure_limits(value, limits=limits)
    try:
        candidate = CandidateIntakeV1.model_validate(value)
    except ValidationError:
        raise BoundaryValidationError("invalid_candidate") from None
    require_structure_limits(candidate, limits=limits)
    if candidate.session_id != session.session_metadata.session_id:
        raise BoundaryValidationError("session_mismatch")
    checker = PIIBoundaryChecker(max_text_bytes=limits.max_text_bytes)
    for observation in candidate.observations:
        _require_observation_text(observation, checker)
    checker.require_text(candidate.extraction_provenance.adapter_name)
    checker.require_text(candidate.extraction_provenance.adapter_version)
    if candidate.human_review is not None:
        checker.require_text(candidate.human_review.reviewer_id)
    return candidate


def _require_json_depth(body: str, maximum: int) -> None:
    """Bound bracket nesting before the recursive JSON decoder, ignoring strings."""
    depth = 0
    in_string = False
    escaped = False
    for char in body:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
            if depth > maximum:
                raise BoundaryValidationError("payload_depth_limit")
        elif char in "}]":
            depth -= 1


def validate_ingestion_envelope(
    value: object, *, limits: ValidationLimits = DEFAULT_LIMITS,
) -> IngestionEnvelopeV1:
    """Check transport syntax and core resource limits; does not establish approval."""
    if isinstance(value, IngestionEnvelopeV1):
        body = value.body
    elif isinstance(value, dict):
        body = value.get("body")
    else:
        raise BoundaryValidationError("invalid_ingestion_envelope")
    if not isinstance(body, str):
        raise BoundaryValidationError("invalid_ingestion_envelope")
    _utf8_size(body, limits.max_body_bytes)
    _require_json_depth(body, limits.max_depth)
    try:
        # The envelope schema checks duplicate keys, finite numbers, and object root.
        envelope = IngestionEnvelopeV1.model_validate(value)
        parsed = json.loads(envelope.body)
    except (ValidationError, ValueError, RecursionError):
        raise BoundaryValidationError("invalid_ingestion_envelope") from None
    # Also reject escaped lone surrogates in decoded keys/values before returning.
    require_structure_limits(parsed, limits=limits)
    return envelope
