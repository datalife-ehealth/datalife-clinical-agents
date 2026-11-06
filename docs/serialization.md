# Approved-candidate serialization

`serialize_approved_candidate` builds an `IngestionEnvelopeV1` for reviewable output.
It never sends an HTTP request, writes a database, changes workflow state, or
automatically runs when the patient approves a revision.

## Responsibilities

The implementation uses three small layers:

- `validation.py` applies schema checks, text identifier rules, session binding,
  and resource limits. It does not make approval decisions.
- `state_machine.py` controls transitions and reviewer authorization using trusted
  session context. It records whether this instance actually approved the current
  revision.
- `serializer.py` explicitly requests that approved current revision, repeats
  boundary validation, and encodes it into the core request shape.

The serializer accepts a `StateMachine` and an `expected_revision_id`, not an
arbitrary candidate or a caller-supplied subject key. `get_approved_candidate`
requires current approval performed by this machine instance. A pre-approved
snapshot loaded into a fresh instance is insufficient; restoring authorization
across restarts would need a separately designed trusted mechanism.

## Output contract

The outer request contains exactly:

| Field | Value |
| --- | --- |
| `subject_key` | The opaque key from the workflow's bound source session. |
| `kind` | `"json"`. |
| `media_type` | `"application/json"`. |
| `body` | A string containing the JSON representation of the approved `CandidateIntakeV1`. |

The body uses the existing candidate v1 contract, including candidate/revision IDs,
parent reference, observation versions and types, self-report provenance,
uncertainty, extraction provenance, approved status, and revision-bound human review.
It excludes the source report and does not copy `SessionInputV1` into the body.
The subject key appears only in the outer envelope.

This is a local clinical-agents body contract within the core's general JSON
ingestion contract. It does not assume the core implements candidate-specific
authorization. The core separately applies its own parsing and PII policy; local
success is not a promise that a differently configured core will accept the output.

Encoding uses sorted keys, compact separators, UTF-8 text, and disallows nonfinite
numbers. Identical validated candidates produce identical body strings. Encoding
is streamed against the byte budget, then the completed envelope is revalidated
against the configured body-size, depth, and node limits. No content is truncated,
redacted, or silently dropped to fit those limits.

## Synthetic example

```python
from datetime import datetime, timezone
from uuid import UUID

from datalife_clinical_agents.schemas import (
    CandidateIntakeV1, HumanReview, ReviewStatus, SessionInputV1,
)
from datalife_clinical_agents.serializer import serialize_approved_candidate
from datalife_clinical_agents.state_machine import StateMachine

session_id, revision_id = UUID(int=1), UUID(int=2)
timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
source = SessionInputV1(
    subject_key="synthetic-subject-001",
    intake_input={"raw_text": "Synthetic report: headache for three days."},
    session_metadata={"session_id": session_id, "timestamp": timestamp},
)
draft = CandidateIntakeV1(
    candidate_id=UUID(int=3), revision_id=revision_id, revision_number=1,
    session_id=session_id,
    extraction_provenance={"adapter_name": "synthetic_fixture", "adapter_version": "1"},
    observations=[{
        "provenance": {"session_id": session_id},
        "value_unit": {"observation_type": "symptom", "symptom": "headache"},
        "uncertainty": {"is_uncertain": True, "abstained": False},
    }],
)
workflow = StateMachine(
    candidate_intake=draft, session_input=source,
    authorized_reviewer_id="synthetic-patient-001",
)
workflow.submit_for_review(operation_id=UUID(int=10), expected_revision_id=revision_id)
workflow.approve(
    HumanReview(
        revision_id=revision_id, reviewer_id="synthetic-patient-001",
        decision=ReviewStatus.APPROVED, reviewed_at=timestamp,
    ),
    operation_id=UUID(int=11), expected_revision_id=revision_id,
)

# This separate call only constructs data. No network write occurs.
envelope = serialize_approved_candidate(workflow, expected_revision_id=revision_id)
assert envelope.kind == "json"
assert "raw_text" not in envelope.body
```

## Rejection and integration limits

Draft, pending, cancelled, rejected, superseded, and externally claimed approvals
cannot produce an envelope through this entry point. Schema and privacy rules
are checked again, so a matching human decision never exempts content from them.
Serialization failures raise `SerializationError` with a fixed message and return
no partial output. The module logs neither clinical data nor validation details.

The hosting application must authenticate patients, authorize session access, and
supply trusted opaque identifiers. The machine and serializer are synchronous;
the owner must serialize access to one instance. Approval evidence and retry
records last only for that instance, and no durable storage or extra audit system
is introduced. Name detection retains its [documented limits](validation.md).
