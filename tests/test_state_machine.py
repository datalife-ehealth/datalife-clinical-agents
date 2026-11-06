"""Synthetic workflow tests, including failures, correction isolation, and retries."""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from datalife_clinical_agents.schemas import (
    CandidateIntakeV1, HumanReview, ObservationV1, ReviewStatus, SessionInputV1,
)
from datalife_clinical_agents.state_machine import StateMachine, WorkflowError


SESSION = UUID(int=1)
REVISION = UUID(int=2)
NEW_REVISION = UUID(int=3)
OPERATION = UUID(int=10)
REVIEWER = "synthetic-patient-001"


def session():
    return SessionInputV1(
        subject_key="synthetic-subject-001",
        intake_input={"raw_text": "Synthetic headache report."},
        session_metadata={"session_id": SESSION, "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)},
    )


def observation(symptom="synthetic headache", *, abstained=False):
    return ObservationV1(
        provenance={"session_id": SESSION},
        value_unit={"observation_type": "symptom", "symptom": symptom},
        uncertainty={
            "is_uncertain": True,
            "abstained": abstained,
            "abstained_reason": "Synthetic ambiguous report." if abstained else None,
        },
    )


def review(decision=ReviewStatus.APPROVED, *, revision_id=REVISION, reviewer_id=REVIEWER):
    return HumanReview(
        revision_id=revision_id, reviewer_id=reviewer_id, decision=decision,
        reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def candidate(status=ReviewStatus.DRAFT, *, observations=None):
    data = {
        "candidate_id": UUID(int=4), "session_id": SESSION,
        "revision_id": REVISION, "revision_number": 1,
        "review_status": status,
        "observations": [observation()] if observations is None else observations,
        "extraction_provenance": {"adapter_name": "synthetic_fixture", "adapter_version": "1"},
    }
    if status in (ReviewStatus.APPROVED, ReviewStatus.REJECTED):
        data["human_review"] = review(status)
    return CandidateIntakeV1.model_validate(data)


def machine(status=ReviewStatus.DRAFT, *, observations=None):
    return StateMachine(
        candidate_intake=candidate(status, observations=observations),
        authorized_reviewer_id=REVIEWER,
        session_input=session(),
    )


def invoke(workflow, action, *, operation_id=OPERATION, expected_revision_id=REVISION):
    args = {"operation_id": operation_id, "expected_revision_id": expected_revision_id}
    if action == "submit":
        return workflow.submit_for_review(**args)
    if action == "approve":
        return workflow.approve(review(), **args)
    if action == "reject":
        return workflow.reject(review(ReviewStatus.REJECTED), **args)
    if action == "cancel":
        return workflow.cancel(**args)
    return workflow.correct(NEW_REVISION, [observation("synthetic corrected symptom")], **args)


ALLOWED = {
    "submit": {ReviewStatus.DRAFT},
    "approve": {ReviewStatus.PENDING},
    "reject": {ReviewStatus.PENDING},
    "cancel": {ReviewStatus.DRAFT, ReviewStatus.PENDING},
    "correct": {ReviewStatus.DRAFT, ReviewStatus.PENDING},
}
RESULT = {
    "submit": ReviewStatus.PENDING, "approve": ReviewStatus.APPROVED,
    "reject": ReviewStatus.REJECTED, "cancel": ReviewStatus.CANCELLED,
    "correct": ReviewStatus.DRAFT,
}


@pytest.mark.parametrize("status", list(ReviewStatus))
@pytest.mark.parametrize("action", list(ALLOWED))
def test_transition_table_and_unchanged_input_snapshot(status, action):
    workflow = machine(status)
    original = workflow.candidate_intake
    original_json = original.model_dump_json()
    if status in ALLOWED[action]:
        result = invoke(workflow, action)
        assert result.review_status is RESULT[action]
        assert workflow.candidate_intake == result
        assert result.observations[0].uncertainty.is_uncertain is True
    else:
        with pytest.raises(WorkflowError, match="^invalid_transition$"):
            invoke(workflow, action)
        assert workflow.candidate_intake.model_dump_json() == original_json
    assert original.model_dump_json() == original_json


@pytest.mark.parametrize("observations", [[], [observation(abstained=True)]])
def test_submit_validates_readiness_without_partial_state_change(observations):
    workflow = machine(observations=observations)
    before = workflow.candidate_intake
    with pytest.raises(WorkflowError, match="^candidate_validation_failed$"):
        invoke(workflow, "submit")
    assert workflow.candidate_intake == before
    assert workflow.revision_history == (before,)


@pytest.mark.parametrize("human_review,code", [
    (review(ReviewStatus.REJECTED), "candidate_validation_failed"),
    (review(revision_id=NEW_REVISION), "candidate_validation_failed"),
    (review(reviewer_id="synthetic-other-patient"), "unauthorized_reviewer"),
    (None, "invalid_human_review"),
    ({"decision": "approved"}, "invalid_human_review"),
])
def test_approval_checks_decision_revision_and_authorized_reviewer(human_review, code):
    workflow = machine(ReviewStatus.PENDING)
    before = workflow.candidate_intake
    with pytest.raises(WorkflowError, match=f"^{code}$"):
        workflow.approve(human_review, operation_id=OPERATION, expected_revision_id=REVISION)
    assert workflow.candidate_intake == before


def test_rejection_rejects_an_approval_record():
    workflow = machine(ReviewStatus.PENDING)
    with pytest.raises(WorkflowError, match="^candidate_validation_failed$"):
        workflow.reject(review(), operation_id=OPERATION, expected_revision_id=REVISION)
    assert workflow.candidate_intake.review_status is ReviewStatus.PENDING


def test_correction_records_lineage_and_preserves_old_content():
    workflow = machine(ReviewStatus.PENDING)
    old = workflow.candidate_intake
    replacements = [observation("synthetic corrected symptom", abstained=True)]
    result = workflow.correct(
        NEW_REVISION, replacements, operation_id=OPERATION, expected_revision_id=REVISION,
    )
    assert result.candidate_id == old.candidate_id
    assert result.session_id == old.session_id
    assert result.extraction_provenance == old.extraction_provenance
    assert result.revision_id == NEW_REVISION
    assert result.parent_revision_id == REVISION
    assert result.revision_number == 2
    assert result.review_status is ReviewStatus.DRAFT
    assert result.human_review is None
    assert result.observations[0].uncertainty.abstained is True
    assert workflow.revision_history == (old, result)
    replacements[0].value_unit.symptom = "changed outside machine"
    result.observations[0].value_unit.symptom = "another outside change"
    assert workflow.candidate_intake.observations[0].value_unit.symptom == "synthetic corrected symptom"
    assert old.observations[0].value_unit.symptom == "synthetic headache"


def test_correction_cannot_mix_sessions():
    workflow = machine()
    replacement = observation()
    replacement.provenance.session_id = UUID(int=999)
    with pytest.raises(WorkflowError, match="^candidate_validation_failed$"):
        workflow.correct(
            NEW_REVISION, [replacement], operation_id=OPERATION, expected_revision_id=REVISION,
        )
    assert workflow.candidate_intake.revision_id == REVISION


def test_mutated_observation_is_revalidated():
    workflow = machine()
    replacement = observation()
    replacement.uncertainty.confidence_score = 2.0
    with pytest.raises(WorkflowError, match="^invalid_observations$"):
        workflow.correct(
            NEW_REVISION, [replacement], operation_id=OPERATION, expected_revision_id=REVISION,
        )
    assert workflow.candidate_intake.revision_id == REVISION


def test_direct_observation_validation_rechecks_nested_model():
    proposal = observation()
    proposal.uncertainty.confidence_score = 2.0
    with pytest.raises(ValidationError) as caught:
        ObservationV1.model_validate(proposal)
    assert caught.value.errors()[0]["loc"] == ("uncertainty", "confidence_score")


def test_constructor_rejects_mutated_nested_candidate_data():
    initial = candidate()
    initial.observations[0].uncertainty.confidence_score = 2.0
    with pytest.raises(WorkflowError, match="^invalid_candidate$"):
        StateMachine(candidate_intake=initial, authorized_reviewer_id=REVIEWER, session_input=session())


def test_mutated_review_is_revalidated_before_approval():
    workflow = machine(ReviewStatus.PENDING)
    decision = review()
    decision.reviewed_at = datetime(2026, 1, 1)
    with pytest.raises(WorkflowError, match="^invalid_human_review$"):
        workflow.approve(decision, operation_id=OPERATION, expected_revision_id=REVISION)
    assert workflow.candidate_intake.review_status is ReviewStatus.PENDING


def test_mutating_returned_approval_does_not_change_retry_record():
    workflow = machine(ReviewStatus.PENDING)
    result = invoke(workflow, "approve")
    result.observations[0].value_unit.symptom = "outside result mutation"
    result.human_review.reviewer_id = "outside reviewer mutation"
    replay = invoke(workflow, "approve")
    assert replay.observations[0].value_unit.symptom == "synthetic headache"
    assert replay.human_review.reviewer_id == REVIEWER
    assert workflow.candidate_intake == replay


def test_current_and_history_properties_are_detached():
    original = candidate()
    workflow = StateMachine(candidate_intake=original, authorized_reviewer_id=REVIEWER, session_input=session())
    original.observations[0].value_unit.symptom = "outside constructor mutation"
    workflow.candidate_intake.observations[0].value_unit.symptom = "outside property mutation"
    workflow.revision_history[0].observations[0].value_unit.symptom = "outside history mutation"
    assert workflow.candidate_intake.observations[0].value_unit.symptom == "synthetic headache"


@pytest.mark.parametrize("status", [ReviewStatus.DRAFT, ReviewStatus.PENDING])
def test_unchanged_save_does_not_create_revision_or_reset_state(status):
    workflow = machine(status)
    before = workflow.candidate_intake
    result = workflow.correct(
        NEW_REVISION, before.observations, operation_id=OPERATION, expected_revision_id=REVISION,
    )
    assert result == before
    assert workflow.revision_history == (before,)


@pytest.mark.parametrize("action", list(ALLOWED))
def test_identical_retries_return_original_result(action):
    start = ReviewStatus.PENDING if action in ("approve", "reject") else ReviewStatus.DRAFT
    workflow = machine(start)
    first = invoke(workflow, action)
    history = workflow.revision_history
    retry = invoke(workflow, action)
    assert retry == first
    assert retry is not first
    assert workflow.revision_history == history


@pytest.mark.parametrize("action", list(ALLOWED))
def test_new_request_from_old_revision_is_rejected(action):
    workflow = machine()
    invoke(workflow, "correct")
    before = workflow.candidate_intake
    with pytest.raises(WorkflowError, match="^stale_revision$"):
        invoke(workflow, action, operation_id=UUID(int=11))
    assert workflow.candidate_intake == before


def test_old_successful_retry_does_not_rewind_new_revision():
    workflow = machine()
    pending = invoke(workflow, "submit")
    corrected = invoke(workflow, "correct", operation_id=UUID(int=11))
    replay = invoke(workflow, "submit")
    assert replay == pending
    assert workflow.candidate_intake == corrected


def test_operation_id_cannot_be_reused_for_another_action():
    workflow = machine()
    invoke(workflow, "submit")
    with pytest.raises(WorkflowError, match="^operation_id_conflict$"):
        invoke(workflow, "cancel")
    assert workflow.candidate_intake.review_status is ReviewStatus.PENDING


def test_correction_retry_cannot_change_original_payload():
    workflow = machine()
    saved = invoke(workflow, "correct")
    with pytest.raises(WorkflowError, match="^operation_id_conflict$"):
        workflow.correct(
            NEW_REVISION, [observation("different saved text")],
            operation_id=OPERATION, expected_revision_id=REVISION,
        )
    assert workflow.candidate_intake == saved


def test_failed_request_does_not_reserve_operation_id():
    workflow = machine(ReviewStatus.PENDING)
    with pytest.raises(WorkflowError, match="^candidate_validation_failed$"):
        workflow.approve(
            review(ReviewStatus.REJECTED), operation_id=OPERATION, expected_revision_id=REVISION,
        )
    assert invoke(workflow, "approve").review_status is ReviewStatus.APPROVED


def test_prior_revision_id_cannot_be_reused():
    workflow = machine()
    invoke(workflow, "correct")
    with pytest.raises(WorkflowError, match="^revision_id_conflict$"):
        workflow.correct(
            REVISION, [observation("third synthetic revision")],
            operation_id=UUID(int=11), expected_revision_id=NEW_REVISION,
        )


def test_identical_input_and_operation_sequence_is_deterministic():
    first, second = machine(), machine()
    assert invoke(first, "correct").model_dump_json() == invoke(second, "correct").model_dump_json()
    kwargs = {"operation_id": UUID(int=11), "expected_revision_id": NEW_REVISION}
    assert invoke(first, "submit", **kwargs) == invoke(second, "submit", **kwargs)
    decision = review(revision_id=NEW_REVISION)
    args = {"operation_id": UUID(int=12), "expected_revision_id": NEW_REVISION}
    assert first.approve(decision, **args) == second.approve(decision, **args)


@pytest.mark.parametrize("reviewer", [None, "", "   ", 123])
def test_authorized_reviewer_must_be_explicit_nonblank_string(reviewer):
    with pytest.raises(WorkflowError, match="^invalid_authorized_reviewer$"):
        StateMachine(candidate_intake=candidate(), authorized_reviewer_id=reviewer, session_input=session())


def test_failure_does_not_echo_submitted_content():
    workflow = machine(ReviewStatus.PENDING)
    with pytest.raises(WorkflowError) as caught:
        workflow.approve(
            review(reviewer_id="synthetic-private-identifier"),
            operation_id=OPERATION, expected_revision_id=REVISION,
        )
    assert str(caught.value) == "unauthorized_reviewer"
