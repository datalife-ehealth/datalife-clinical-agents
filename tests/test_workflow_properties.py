"""Deterministic families of synthetic sequences exercising workflow invariants.

No random seed or extra testing dependency is needed. Sequence lengths, starting
states, observation values/types, and failure modes vary explicitly below.
"""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from datalife_clinical_agents.schemas import (
    CandidateIntakeV1, HumanReview, ObservationV1, ReviewStatus, SessionInputV1,
)
from datalife_clinical_agents.serializer import serialize_approved_candidate
from datalife_clinical_agents.state_machine import StateMachine, WorkflowError


SESSION = UUID(int=1)
CANDIDATE = UUID(int=2)
FIRST_REVISION = UUID(int=3)
TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
REVIEWER = "synthetic-patient-001"


def _observations(step):
    proposals = [ObservationV1(
        provenance={"session_id": SESSION},
        value_unit={
            "observation_type": "symptom", "symptom": "synthetic headache",
            "duration_days": float(step),
        },
        uncertainty={"is_uncertain": step % 2 == 0, "abstained": False},
    )]
    if step % 2 == 0:
        proposals.append(ObservationV1(
            provenance={"session_id": SESSION},
            value_unit={
                "observation_type": "blood_pressure", "systolic": 120 + step,
                "diastolic": 75 + step,
            },
            uncertainty={"is_uncertain": True, "abstained": False, "confidence_score": 0.75},
        ))
    return proposals


def _workflow():
    source = SessionInputV1(
        subject_key="synthetic-subject-001",
        intake_input={"raw_text": "Synthetic reports of headache and blood pressure readings."},
        session_metadata={"session_id": SESSION, "timestamp": TIME},
    )
    draft = CandidateIntakeV1(
        candidate_id=CANDIDATE, session_id=SESSION, revision_id=FIRST_REVISION,
        revision_number=1, observations=_observations(0),
        extraction_provenance={"adapter_name": "synthetic_fixture", "adapter_version": "1"},
    )
    return StateMachine(
        candidate_intake=draft, session_input=source, authorized_reviewer_id=REVIEWER,
    )


def _assert_failed_save_is_atomic(machine, step, previous_revision):
    before = machine.candidate_intake
    history = machine.revision_history
    proposed_revision = UUID(int=10_000 + step)
    args = {"operation_id": UUID(int=20_000 + step), "expected_revision_id": before.revision_id}
    replacements = _observations(step + 100)
    if step % 3 == 1:
        args["expected_revision_id"] = previous_revision
        code = "stale_revision"
    elif step % 3 == 2:
        proposed_revision = previous_revision
        code = "revision_id_conflict"
    else:
        replacements[0].uncertainty.confidence_score = 2.0
        code = "invalid_observations"
    with pytest.raises(WorkflowError, match=f"^{code}$"):
        machine.correct(proposed_revision, replacements, **args)
    assert machine.candidate_intake == before
    assert machine.revision_history == history


def _exercise_sequence(length, submit_between_saves):
    machine = _workflow()
    saved_operations = []
    revision_ids = [FIRST_REVISION]
    for step in range(1, length + 1):
        previous_revision = revision_ids[-1]
        if submit_between_saves:
            machine.submit_for_review(
                operation_id=UUID(int=1_000 + step), expected_revision_id=previous_revision,
            )
        previous = machine.candidate_intake
        previous_json = previous.model_dump_json()
        new_revision = UUID(int=100 + step)
        replacements = _observations(step)
        args = {"operation_id": UUID(int=2_000 + step), "expected_revision_id": previous_revision}
        saved = machine.correct(new_revision, replacements, **args)
        saved_operations.append((new_revision, replacements, args, saved.model_dump_json()))
        revision_ids.append(new_revision)

        assert saved.candidate_id == CANDIDATE
        assert saved.session_id == SESSION
        assert saved.parent_revision_id == previous_revision
        assert saved.revision_number == step + 1
        assert saved.review_status is ReviewStatus.DRAFT
        assert saved.human_review is None
        assert saved.observations == replacements
        assert previous.model_dump_json() == previous_json
        assert [item.revision_id for item in machine.revision_history] == revision_ids
        assert [item.revision_number for item in machine.revision_history] == list(range(1, step + 2))

        # Repeating a save never adds a revision or changes the current snapshot.
        assert machine.correct(new_revision, replacements, **args) == saved
        assert len(machine.revision_history) == step + 1
        _assert_failed_save_is_atomic(machine, step, previous_revision)

        # A changed payload cannot reuse a successful request's identity.
        with pytest.raises(WorkflowError, match="^operation_id_conflict$"):
            machine.correct(new_revision, _observations(step + 100), **args)
        assert machine.candidate_intake == saved

        # Replaying earlier saves after later work must not rewind current state.
        for historical_id, values, arguments, expected_json in saved_operations:
            assert machine.correct(historical_id, values, **arguments).model_dump_json() == expected_json
            assert machine.candidate_intake == saved

    current_revision = revision_ids[-1]
    machine.submit_for_review(operation_id=UUID(int=3_000), expected_revision_id=current_revision)
    decision = HumanReview(
        revision_id=current_revision, reviewer_id=REVIEWER,
        decision=ReviewStatus.APPROVED, reviewed_at=TIME,
    )
    approved = machine.approve(decision, operation_id=UUID(int=3_001), expected_revision_id=current_revision)
    first_id, first_values, first_args, _ = saved_operations[0]
    machine.correct(first_id, first_values, **first_args)
    assert machine.candidate_intake == approved
    assert machine.candidate_intake.human_review.revision_id == current_revision
    body = serialize_approved_candidate(machine, expected_revision_id=current_revision).body
    return body, tuple(item.model_dump_json() for item in machine.revision_history)


@pytest.mark.parametrize("length", [1, 2, 5, 10])
@pytest.mark.parametrize("submit_between_saves", [False, True], ids=["draft-corrections", "review-corrections"])
def test_revision_retry_and_failure_properties_across_sequences(length, submit_between_saves):
    first_run = _exercise_sequence(length, submit_between_saves)
    second_run = _exercise_sequence(length, submit_between_saves)
    assert first_run == second_run
