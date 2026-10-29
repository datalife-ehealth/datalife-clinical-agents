"""Versioned intake contracts; workflow authorization lives outside these models."""

from typing import Annotated, Literal, Self
from uuid import UUID
from enum import Enum
import json
import math

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class Arguments(BaseModel):
    """Shared rules: reject unknown fields and implicit type conversions."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
    )

# Session input
class Modality(str, Enum):
    TEXT = "text"
    AUDIO = "audio_transcript"


class IntakeInput(Arguments):
    """A submitted report; empty drafts are not valid submitted input."""

    raw_text: str = Field(
        min_length=1,
        repr=False,
        description="Patient-provided text or an existing audio transcript.",
    )
    modality: Modality = Field(
        default=Modality.TEXT,
        description="Indicates how the input was captured; audio files are unsupported.",
    )

    @field_validator("raw_text")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("intake text must not be blank")
        # Check without changing the patient's original report.
        return value


class SessionMetaData(Arguments):
    """Created once by trusted application code and reused on retries."""

    session_id: UUID
    timestamp: AwareDatetime


class SessionInputV1(Arguments):
    """A submitted session; validity does not grant approval or ingestion rights."""

    schema_version: Literal["1"] = "1"
    subject_key: str = Field(min_length=4, max_length=64, repr=False)
    intake_input: IntakeInput
    session_metadata: SessionMetaData

    @field_validator("subject_key")
    @classmethod
    def require_nonblank_subject_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("subject key must not be blank")
        return value

# Observations
class ObservationProvenance(Arguments):
    """The report's origin, not proof of clinical verification."""

    source: Literal["self_reported"] = "self_reported"
    session_id: UUID


class SymptomValue(Arguments):
    """Patient-reported symptom text; missing duration stays unknown."""

    observation_type: Literal["symptom"] = "symptom"
    symptom: str | None = Field(default=None, min_length=1, repr=False)
    duration_days: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @field_validator("symptom")
    @classmethod
    def require_nonblank_symptom(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("symptom must not be blank")
        return value


class BloodPressureValue(Arguments):
    """Reported measurements only; no clinical interpretation or invented values."""

    observation_type: Literal["blood_pressure"] = "blood_pressure"
    systolic: int | None = Field(default=None, gt=0)
    diastolic: int | None = Field(default=None, gt=0)
    unit: Literal["mmHg"] = "mmHg"


class ObservationUncertainty(Arguments):
    confidence_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
        description="Optional extraction confidence; not clinical certainty or approval.",
    )
    is_uncertain: bool = Field(
        description="True when the patient expressed doubt; do not infer from confidence.",
    )
    abstained: bool = Field(
        description="True when extraction declines to propose a usable observation.",
    )
    abstained_reason: str | None = Field(
        default=None,
        min_length=1,
        repr=False,
        description="Required explanation for abstention; omit when not abstaining.",
    )

    @model_validator(mode="after")
    def check_abstention_reason(self) -> Self:
        if self.abstained:
            if self.abstained_reason is None or not self.abstained_reason.strip():
                raise ValueError("abstention requires a nonblank reason")
        elif self.abstained_reason is not None:
            raise ValueError("an abstention reason requires abstained=True")
        return self


class ObservationV1(Arguments):
    """A typed extraction proposal that still requires validation and human review."""

    schema_version: Literal["1"] = "1"
    provenance: ObservationProvenance
    value_unit: Annotated[
        SymptomValue | BloodPressureValue,
        Field(discriminator="observation_type"),
    ]
    uncertainty: ObservationUncertainty

    @model_validator(mode="after")
    def require_value_or_abstention(self) -> Self:
        if self.uncertainty.abstained:
            # Retain partial reported data for correction; never invent missing values.
            return self
        if isinstance(self.value_unit, SymptomValue):
            if self.value_unit.symptom is None:
                raise ValueError("missing symptom requires abstention")
        elif self.value_unit.systolic is None or self.value_unit.diastolic is None:
            raise ValueError("incomplete blood pressure requires abstention")
        return self

# Candidate revisions and review snapshots
class ReviewStatus(str, Enum):
    """Workflow state assigned by trusted application code."""

    DRAFT = "drafting"
    PENDING = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class HumanReview(Arguments):
    """Recorded human decision; the workflow must authenticate and authorize it."""

    revision_id: UUID = Field(description="The exact revision reviewed by the human.")
    reviewer_id: str = Field(
        min_length=1,
        repr=False,
        description="Opaque reviewer identifier supplied by trusted authorization code.",
    )
    decision: Literal["approved", "rejected"] = Field(
        description="Recorded human decision; trusted workflow must verify its origin.",
    )
    reviewed_at: AwareDatetime = Field(
        description="Timezone-aware decision time supplied by the trusted workflow.",
    )

    @field_validator("reviewer_id")
    @classmethod
    def require_nonblank_reviewer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reviewer identifier must not be blank")
        return value


class ExtractionProvenance(Arguments):
    """Records which adapter produced the observations; supplied by trusted code."""

    adapter_name: str = Field(
        min_length=1,
        description="Adapter name supplied by trusted application code, e.g. synthetic_fixture.",
    )
    adapter_version: str = Field(
        min_length=1,
        description="Adapter version supplied by trusted application code for reproducibility.",
    )

    @field_validator("adapter_name", "adapter_version")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("adapter name and version must not be blank")
        return value


class CandidateIntakeV1(Arguments):
    """One candidate revision, assembled by trusted code from untrusted observations."""

    schema_version: Literal["1"] = Field(
        default="1", description="Candidate contract version, independent of package version.",
    )
    candidate_id: UUID = Field(
        description="Stable candidate identity, shared by its correction revisions.",
    )
    observations: list[ObservationV1] = Field(
        repr=False,
        description="Proposals from this session, retaining uncertainty and abstentions.",
    )
    revision_id: UUID = Field(
        description="Unique identity for this content revision; corrections need a new ID.",
    )
    parent_revision_id: UUID | None = Field(
        default=None,
        description="Previous revision ID; absent only for the first revision.",
    )
    session_id: UUID = Field(
        description="Source intake session; must match every observation's provenance.",
    )
    revision_number: int = Field(
        ge=1, description="Revision sequence starting at 1; incremented by the workflow.",
    )
    review_status: ReviewStatus = Field(
        default=ReviewStatus.DRAFT,
        description="Trusted workflow state; model or patient input must not set this.",
    )
    extraction_provenance: ExtractionProvenance = Field(
        description="Extraction adapter identity assigned by trusted code, not model output.",
    )
    human_review: HumanReview | None = Field(
        default=None,
        description="Required only for approved/rejected revisions; not authorization proof.",
    )

    @model_validator(mode="after")
    def check_revision_and_review(self) -> Self:
        if self.parent_revision_id == self.revision_id:
            raise ValueError("a revision cannot be its own parent")
        if self.revision_number == 1 and self.parent_revision_id is not None:
            raise ValueError("the first revision cannot have a parent")
        if self.revision_number > 1 and self.parent_revision_id is None:
            raise ValueError("a correction revision requires a parent")

        if any(item.provenance.session_id != self.session_id for item in self.observations):
            raise ValueError("observation provenance must match the candidate session")

        if self.review_status in (ReviewStatus.PENDING, ReviewStatus.APPROVED):
            if not self.observations:
                raise ValueError("reviewable candidates require observations")
            if any(item.uncertainty.abstained for item in self.observations):
                raise ValueError("abstained observations must be resolved before review")

        if self.review_status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED):
            if self.human_review is None:
                raise ValueError("approved or rejected revisions require a human review")
            if self.human_review.revision_id != self.revision_id:
                raise ValueError("human review must refer to the current revision")
            if self.human_review.decision != self.review_status.value:
                raise ValueError("human decision must match the review status")
        elif self.human_review is not None:
            raise ValueError("unreviewed revisions cannot carry a human decision")
        return self

# Core ingestion envelope
class IngestionEnvelopeV1(Arguments):
    """Core-compatible JSON request shape; does not authorize or perform ingestion."""

    subject_key: str = Field(
        min_length=4,
        max_length=64,
        repr=False,
        description="Opaque patient-client subject key, verified by trusted application code.",
    )
    kind: Literal["json"] = Field(
        default="json", description="Only JSON ingestion is supported by this contract.",
    )
    media_type: Literal["application/json"] = Field(
        default="application/json", description="Media type required for JSON ingestion.",
    )
    body: str = Field(
        min_length=1,
        repr=False,
        description="Serialized JSON object, not a dictionary; approval and PII checks are separate.",
    )

    @field_validator("subject_key")
    @classmethod
    def require_nonblank_subject_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("subject key must not be blank")
        return value

    @field_validator("body")
    @classmethod
    def require_json_object(cls, value: str) -> str:
        # Python's JSON decoder otherwise accepts duplicates and NaN/Infinity.
        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = item
            return result

        def reject_constant(token: str) -> float:
            raise ValueError("nonfinite JSON number")

        def finite_float(token: str) -> float:
            number = float(token)
            if not math.isfinite(number):
                raise ValueError("nonfinite JSON number")
            return number

        try:
            value.encode("utf-8")
            parsed = json.loads(
                value,
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
                parse_float=finite_float,
            )
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            # Never reflect JSON fragments or parser details in the error message.
            raise ValueError("body must contain valid UTF-8 JSON with unique keys and finite numbers") from None
        if not isinstance(parsed, dict):
            raise ValueError("body must contain a JSON object")
        # Validation must not rewrite text that will later be hashed by the core.
        return value
