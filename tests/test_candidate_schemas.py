"""Candidate snapshot invariants, using synthetic observations and opaque IDs."""

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from datalife_clinical_agents.schemas import CandidateIntakeV1, HumanReview, ReviewStatus


SESSION_ID = UUID("00000000-0000-4000-8000-000000000001")
REVISION_ID = UUID("00000000-0000-4000-8000-000000000002")
OTHER_REVISION_ID = UUID("00000000-0000-4000-8000-000000000003")
CANDIDATE_ID = UUID("00000000-0000-4000-8000-000000000004")


@pytest.fixture
def candidate_data():
    return {
        "candidate_id": CANDIDATE_ID,
        "revision_id": REVISION_ID,
        "revision_number": 1,
        "session_id": SESSION_ID,
        "extraction_provenance": {
            "adapter_name": "synthetic_fixture",
            "adapter_version": "1",
        },
        "observations": [{
            "provenance": {"session_id": SESSION_ID},
            "value_unit": {"observation_type": "symptom", "symptom": "headache"},
            "uncertainty": {"is_uncertain": True, "abstained": False},
        }],
    }


@pytest.fixture
def human_review():
    return {
        "revision_id": REVISION_ID,
        "reviewer_id": "synthetic-reviewer-001",
        "decision": ReviewStatus.APPROVED,
        "reviewed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }


def test_new_candidate_defaults_to_draft_and_string_version(candidate_data):
    candidate = CandidateIntakeV1.model_validate(candidate_data)
    assert candidate.schema_version == "1"
    assert candidate.model_dump(mode="json")["schema_version"] == "1"
    assert candidate.review_status is ReviewStatus.DRAFT
    assert candidate.parent_revision_id is None
    assert candidate.human_review is None
    assert candidate.observations[0].uncertainty.is_uncertain is True
    assert candidate.extraction_provenance.adapter_name == "synthetic_fixture"
    assert candidate.extraction_provenance.adapter_version == "1"


@pytest.mark.parametrize("field", [
    "candidate_id", "revision_id", "revision_number", "session_id", "observations",
    "extraction_provenance",
])
def test_requires_explicit_candidate_fields(candidate_data, field):
    del candidate_data[field]
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("number", [0, -1, True, 1.5, "1", OTHER_REVISION_ID])
def test_requires_positive_integer_revision_number(candidate_data, number):
    candidate_data["revision_number"] = number
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("version", [1, "2", None])
def test_rejects_invalid_candidate_versions(candidate_data, version):
    candidate_data["schema_version"] = version
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_first_revision_cannot_have_parent(candidate_data):
    candidate_data["parent_revision_id"] = OTHER_REVISION_ID
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_correction_requires_parent(candidate_data):
    candidate_data["revision_number"] = 2
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_revision_cannot_reference_itself(candidate_data):
    candidate_data.update(revision_number=2, parent_revision_id=REVISION_ID)
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_correction_keeps_candidate_identity_but_has_new_revision(candidate_data):
    original = CandidateIntakeV1.model_validate(candidate_data)
    candidate_data.update(
        revision_id=OTHER_REVISION_ID,
        parent_revision_id=REVISION_ID,
        revision_number=2,
    )
    candidate_data["observations"][0]["value_unit"]["symptom"] = "synthetic corrected report"
    correction = CandidateIntakeV1.model_validate(candidate_data)
    assert correction.candidate_id == original.candidate_id
    assert correction.parent_revision_id == original.revision_id
    assert correction.revision_id != original.revision_id
    assert correction.review_status is ReviewStatus.DRAFT
    assert correction.human_review is None
    assert original.observations[0].value_unit.symptom == "headache"


def test_rejects_cross_session_observation(candidate_data):
    candidate_data["observations"][0]["provenance"]["session_id"] = OTHER_REVISION_ID
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("status", [ReviewStatus.DRAFT, ReviewStatus.CANCELLED])
def test_empty_nonreviewable_snapshot_is_allowed(candidate_data, status):
    candidate_data.update(observations=[], review_status=status)
    assert CandidateIntakeV1.model_validate(candidate_data).observations == []


@pytest.mark.parametrize("status", [ReviewStatus.PENDING, ReviewStatus.APPROVED])
def test_reviewable_candidate_cannot_be_empty(candidate_data, human_review, status):
    candidate_data.update(observations=[], review_status=status)
    if status is ReviewStatus.APPROVED:
        candidate_data["human_review"] = human_review
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("status", [ReviewStatus.PENDING, ReviewStatus.APPROVED])
def test_reviewable_candidate_cannot_contain_abstention(candidate_data, human_review, status):
    candidate_data["observations"][0]["uncertainty"].update(
        abstained=True, abstained_reason="Synthetic ambiguous report.",
    )
    candidate_data["review_status"] = status
    if status is ReviewStatus.APPROVED:
        candidate_data["human_review"] = human_review
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_draft_retains_partial_abstained_measurement(candidate_data):
    candidate_data["observations"][0]["value_unit"] = {
        "observation_type": "blood_pressure", "systolic": 145,
    }
    candidate_data["observations"][0]["uncertainty"].update(
        abstained=True, abstained_reason="Diastolic value was not reported.",
    )
    candidate = CandidateIntakeV1.model_validate(candidate_data)
    assert candidate.observations[0].value_unit.systolic == 145
    assert candidate.observations[0].value_unit.diastolic is None
    assert candidate.observations[0].uncertainty.abstained is True


@pytest.mark.parametrize("status", [ReviewStatus.APPROVED, ReviewStatus.REJECTED])
def test_human_decision_required_for_reviewed_states(candidate_data, status):
    candidate_data["review_status"] = status
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("status", [ReviewStatus.APPROVED, ReviewStatus.REJECTED])
def test_accepts_matching_human_review_snapshot(candidate_data, human_review, status):
    human_review["decision"] = status
    candidate_data.update(review_status=status, human_review=human_review)
    candidate = CandidateIntakeV1.model_validate(candidate_data)
    assert candidate.human_review.revision_id == candidate.revision_id
    assert candidate.human_review.decision is status
    assert candidate.model_dump(mode="json")["human_review"]["decision"] == status.value
    assert candidate.observations[0].uncertainty.is_uncertain is True
    assert CandidateIntakeV1.model_validate_json(candidate.model_dump_json()) == candidate


@pytest.mark.parametrize("status", [ReviewStatus.DRAFT, ReviewStatus.PENDING, ReviewStatus.CANCELLED])
def test_human_review_rejects_nondecision_statuses(human_review, status):
    human_review["decision"] = status
    with pytest.raises(ValidationError) as caught:
        HumanReview.model_validate(human_review)
    assert caught.value.errors()[0]["loc"] == ("decision",)
    assert caught.value.errors()[0]["type"] == "literal_error"


def test_rejects_review_from_old_revision(candidate_data, human_review):
    candidate_data.update(
        revision_id=OTHER_REVISION_ID,
        parent_revision_id=REVISION_ID,
        revision_number=2,
        review_status=ReviewStatus.APPROVED,
        human_review=human_review,
    )
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_rejects_decision_status_mismatch(candidate_data, human_review):
    candidate_data.update(review_status=ReviewStatus.REJECTED, human_review=human_review)
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("status", [ReviewStatus.DRAFT, ReviewStatus.PENDING, ReviewStatus.CANCELLED])
def test_unreviewed_state_cannot_retain_approval(candidate_data, human_review, status):
    candidate_data.update(review_status=status, human_review=human_review)
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("reviewer", ["", "   ", 123])
def test_rejects_invalid_reviewer_identifier(candidate_data, human_review, reviewer):
    human_review["reviewer_id"] = reviewer
    candidate_data.update(review_status=ReviewStatus.APPROVED, human_review=human_review)
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


def test_review_timestamp_must_have_timezone(candidate_data, human_review):
    human_review["reviewed_at"] = datetime(2026, 1, 1)
    candidate_data.update(review_status=ReviewStatus.APPROVED, human_review=human_review)
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate(candidate_data)


@pytest.mark.parametrize("section", [None, "human_review", "extraction_provenance"])
def test_unknown_fields_fail_closed(candidate_data, human_review, section):
    candidate_data.update(review_status=ReviewStatus.APPROVED, human_review=human_review)
    target = candidate_data if section is None else candidate_data[section]
    target["bypass_validation"] = True
    with pytest.raises(ValidationError) as caught:
        CandidateIntakeV1.model_validate(candidate_data)
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())


def test_unknown_json_review_status_fails_closed(candidate_data):
    candidate = CandidateIntakeV1.model_validate(candidate_data)
    payload = candidate.model_dump(mode="json")
    payload["review_status"] = "auto_approved"
    with pytest.raises(ValidationError):
        CandidateIntakeV1.model_validate_json(json.dumps(payload))


def test_repeat_validation_keeps_candidate_revision_identity(candidate_data):
    first = CandidateIntakeV1.model_validate(candidate_data)
    retry = CandidateIntakeV1.model_validate(candidate_data)
    assert first.model_dump_json() == retry.model_dump_json()
