"""Deterministic, in-memory transitions for one trusted candidate session."""

from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError

from .schemas import CandidateIntakeV1, HumanReview, ObservationV1, ReviewStatus, SessionInputV1
from .validation import (
    DEFAULT_LIMITS, BoundaryValidationError, ValidationLimits,
    require_structure_limits, validate_candidate, validate_observation, validate_session_input,
)


class WorkflowError(ValueError):
    """A stable error code without submitted content or sensitive identifiers."""


@dataclass
class _OperationResult:
    request: tuple[object, ...]
    candidate: CandidateIntakeV1


def _snapshot(candidate: CandidateIntakeV1) -> CandidateIntakeV1:
    """Detach an already validated internal candidate without revalidating it."""
    return candidate.model_copy(deep=True)


class StateMachine:
    """Trusted workflow service, not a frontend request or an extraction schema.

    The caller must bind authorized_reviewer_id to this candidate's session using
    authenticated application context. This class does not authenticate patients.
    Use one instance per candidate and serialize access to it.
    """

    def __init__(
        self, *, candidate_intake: CandidateIntakeV1, authorized_reviewer_id: str,
        session_input: SessionInputV1, limits: ValidationLimits = DEFAULT_LIMITS,
    ) -> None:
        if not isinstance(authorized_reviewer_id, str) or not authorized_reviewer_id.strip():
            raise WorkflowError("invalid_authorized_reviewer")
        if not isinstance(limits, ValidationLimits):
            raise WorkflowError("invalid_validation_limits")
        if not isinstance(candidate_intake, CandidateIntakeV1):
            raise WorkflowError("invalid_candidate")
        try:
            self._session = validate_session_input(session_input, limits=limits)
        except BoundaryValidationError:
            raise WorkflowError("session_boundary_rejected") from None
        self._limits = limits
        try:
            self._candidate = validate_candidate(candidate_intake, session_input=self._session, limits=limits)
        except BoundaryValidationError as error:
            code = "invalid_candidate" if str(error) == "invalid_candidate" else "candidate_boundary_rejected"
            raise WorkflowError(code) from None
        self._authorized_reviewer_id = authorized_reviewer_id
        # A loaded snapshot claiming approval is not evidence of a decision here.
        self._approved_revision_id: UUID | None = None
        # Content revisions and retry results are process-local, not an audit log.
        self._revisions = {self._candidate.revision_id: _snapshot(self._candidate)}
        self._operations: dict[UUID, _OperationResult] = {}

    @property
    def candidate_intake(self) -> CandidateIntakeV1:
        """Return a detached snapshot so callers cannot mutate the current state."""
        return _snapshot(self._candidate)

    @property
    def revision_history(self) -> tuple[CandidateIntakeV1, ...]:
        """Latest workflow snapshot of each content revision seen by this instance."""
        return tuple(_snapshot(item) for item in self._revisions.values())

    @property
    def session_input(self) -> SessionInputV1:
        """Detached source context; never include its raw report in the output body."""
        return self._session.model_copy(deep=True)

    @property
    def validation_limits(self) -> ValidationLimits:
        """The same immutable resource configuration used for review and serialization."""
        return self._limits

    def get_approved_candidate(self, *, expected_revision_id: UUID) -> CandidateIntakeV1:
        """Release only the current revision approved through this machine instance."""
        if not isinstance(expected_revision_id, UUID) or expected_revision_id != self._candidate.revision_id:
            raise WorkflowError("stale_revision")
        if (self._candidate.review_status is not ReviewStatus.APPROVED
                or self._approved_revision_id != expected_revision_id):
            raise WorkflowError("approval_required")
        if self._candidate.human_review.reviewer_id != self._authorized_reviewer_id:
            raise WorkflowError("unauthorized_reviewer")
        return _snapshot(self._candidate)

    def submit_for_review(
        self, *, operation_id: UUID, expected_revision_id: UUID,
    ) -> CandidateIntakeV1:
        return self._apply("submit", operation_id, expected_revision_id)

    def approve(
        self, human_review: HumanReview, *, operation_id: UUID, expected_revision_id: UUID,
    ) -> CandidateIntakeV1:
        return self._apply("approve", operation_id, expected_revision_id, human_review=human_review)

    def reject(
        self, human_review: HumanReview, *, operation_id: UUID, expected_revision_id: UUID,
    ) -> CandidateIntakeV1:
        return self._apply("reject", operation_id, expected_revision_id, human_review=human_review)

    def cancel(
        self, *, operation_id: UUID, expected_revision_id: UUID,
    ) -> CandidateIntakeV1:
        return self._apply("cancel", operation_id, expected_revision_id)

    def correct(
        self, revision_id: UUID, observations: list[ObservationV1], *,
        operation_id: UUID, expected_revision_id: UUID,
    ) -> CandidateIntakeV1:
        """Save replacement observations as a draft revision; unchanged content is a no-op."""
        return self._apply(
            "correct", operation_id, expected_revision_id,
            revision_id=revision_id, observations=observations,
        )

    def _apply(
        self, action: str, operation_id: UUID, expected_revision_id: UUID, *,
        human_review: HumanReview | None = None, revision_id: UUID | None = None,
        observations: list[ObservationV1] | None = None,
    ) -> CandidateIntakeV1:
        """Validate inputs, check retries and transitions, then commit one complete update."""
        if not isinstance(operation_id, UUID) or not isinstance(expected_revision_id, UUID):
            raise WorkflowError("invalid_operation_identifiers")

        # Type annotations do not validate Python method arguments at runtime.
        review = None
        replacements = None
        if action in ("approve", "reject"):
            if not isinstance(human_review, HumanReview):
                raise WorkflowError("invalid_human_review")
            try:
                require_structure_limits(human_review, limits=self._limits)
            except BoundaryValidationError:
                raise WorkflowError("review_boundary_rejected") from None
            try:
                review = HumanReview.model_validate(human_review)
            except ValidationError:
                raise WorkflowError("invalid_human_review") from None
            if review.reviewer_id != self._authorized_reviewer_id:
                raise WorkflowError("unauthorized_reviewer")
        if action == "correct":
            if not isinstance(revision_id, UUID):
                raise WorkflowError("invalid_revision_id")
            if not isinstance(observations, list):
                raise WorkflowError("invalid_observations")
            try:
                require_structure_limits(observations, limits=self._limits)
            except BoundaryValidationError:
                raise WorkflowError("observation_boundary_rejected") from None
            if any(not isinstance(item, ObservationV1) for item in observations):
                raise WorkflowError("invalid_observations")
            try:
                replacements = [
                    validate_observation(item, limits=self._limits)
                    for item in observations
                ]
            except BoundaryValidationError as error:
                code = "invalid_observations" if str(error) == "invalid_observation" else "observation_boundary_rejected"
                raise WorkflowError(code) from None

        request = (
            action, expected_revision_id, revision_id,
            review.model_dump_json() if review is not None else None,
            tuple(item.model_dump_json() for item in replacements)
            if replacements is not None else None,
        )
        previous = self._operations.get(operation_id)
        if previous is not None:
            if previous.request != request:
                raise WorkflowError("operation_id_conflict")
            # A delayed retry returns its original result without rewinding current state.
            return _snapshot(previous.candidate)

        current = self._candidate
        if expected_revision_id != current.revision_id:
            raise WorkflowError("stale_revision")
        allowed_states = {
            "submit": (ReviewStatus.DRAFT,),
            "approve": (ReviewStatus.PENDING,),
            "reject": (ReviewStatus.PENDING,),
            "cancel": (ReviewStatus.DRAFT, ReviewStatus.PENDING),
            "correct": (ReviewStatus.DRAFT, ReviewStatus.PENDING),
        }
        if action not in allowed_states or current.review_status not in allowed_states[action]:
            raise WorkflowError("invalid_transition")

        data = current.model_dump()
        if action == "correct":
            if revision_id in self._revisions or revision_id == current.parent_revision_id:
                raise WorkflowError("revision_id_conflict")
            # An unchanged save leaves revision identity and review state intact.
            if replacements != current.observations:
                data.update(
                    observations=replacements,
                    revision_id=revision_id,
                    parent_revision_id=current.revision_id,
                    revision_number=current.revision_number + 1,
                    review_status=ReviewStatus.DRAFT,
                    human_review=None,
                )
        else:
            next_status = {
                "submit": ReviewStatus.PENDING,
                "approve": ReviewStatus.APPROVED,
                "reject": ReviewStatus.REJECTED,
                "cancel": ReviewStatus.CANCELLED,
            }[action]
            data.update(
                review_status=next_status,
                human_review=review,
            )
        try:
            updated = validate_candidate(data, session_input=self._session, limits=self._limits)
        except BoundaryValidationError as error:
            # Do not expose a structured Pydantic error containing clinical input.
            code = "candidate_validation_failed" if str(error) == "invalid_candidate" else "candidate_boundary_rejected"
            raise WorkflowError(code) from None

        # All fallible validation happens before state or retry results are changed.
        history_snapshot = _snapshot(updated)
        operation_result = _OperationResult(request, _snapshot(updated))
        returned_snapshot = _snapshot(updated)
        self._candidate = updated
        self._approved_revision_id = updated.revision_id if action == "approve" else None
        self._revisions[updated.revision_id] = history_snapshot
        self._operations[operation_id] = operation_result
        return returned_snapshot
