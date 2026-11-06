"""Build a candidate core envelope after workflow approval, without network writes."""

import json
from uuid import UUID

from pydantic_core import PydanticSerializationError

from .schemas import IngestionEnvelopeV1
from .state_machine import StateMachine, WorkflowError
from .validation import (
    BoundaryValidationError, validate_candidate, validate_ingestion_envelope,
    validate_session_input,
)


class SerializationError(ValueError):
    """An input-free reason why no ingestion envelope could be produced."""


def serialize_approved_candidate(
    workflow: StateMachine, *, expected_revision_id: UUID,
) -> IngestionEnvelopeV1:
    """Recheck the approved current revision and return an envelope; never send it.

    Accept the trusted workflow, not an arbitrary externally supplied candidate
    claiming approval. Source text is checked again but excluded from the body.
    """
    if not isinstance(workflow, StateMachine):
        raise SerializationError("trusted_workflow_required")
    try:
        current = workflow.get_approved_candidate(expected_revision_id=expected_revision_id)
    except WorkflowError:
        raise SerializationError("approved_current_revision_required") from None

    limits = workflow.validation_limits
    try:
        session = validate_session_input(workflow.session_input, limits=limits)
        candidate = validate_candidate(current, session_input=session, limits=limits)
        # Stream encoding so the output budget is enforced before building a large string.
        encoder = json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        chunks = []
        size = 0
        for chunk in encoder.iterencode(candidate.model_dump(mode="json")):
            size += len(chunk.encode("utf-8"))
            if size > limits.max_body_bytes:
                raise BoundaryValidationError("payload_too_large")
            chunks.append(chunk)
        return validate_ingestion_envelope({
            "subject_key": session.subject_key,
            "kind": "json",
            "media_type": "application/json",
            "body": "".join(chunks),
        }, limits=limits)
    except (BoundaryValidationError, ValueError, TypeError, UnicodeError,
            RecursionError, PydanticSerializationError):
        raise SerializationError("serialization_boundary_rejected") from None
