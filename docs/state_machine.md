# Deterministic intake state machine

`state_machine.py` operates on one candidate in memory. The schemas describe valid
snapshots; the machine checks which operation may produce the next snapshot.
It performs no extraction, network calls, persistence, or clinical decisions.
Construction requires `session_input` as well as the candidate and authorized
reviewer. The validated source session is bound to the candidate's session ID;
its opaque subject key is later used by the serializer.

`StateMachine` is a regular Python class because it manages behavior and private
retry records. Its inputs and outputs remain Pydantic models. The five public
methods share `_apply`, which checks arguments, checks retry identity, checks the
current revision and state, validates the proposed candidate, and only then
updates the machine. `model_copy(update=...)` is not used as a validation boundary.

All schema models inherit `revalidate_instances="always"` from `Arguments`.
Incoming candidates, reviews, and observations can therefore be passed directly
to `model_validate` while still rechecking nested values. A transition uses
`model_dump()` to prepare its field-update dictionary and validates the completed
proposal. Already validated internal snapshots use `model_copy(deep=True)` for
independent storage and return values without repeating validation. Deep copying
does not validate changes and is used only after validation succeeds.

## Transitions

| Operation | Allowed starting states | Result |
| --- | --- | --- |
| `submit_for_review` | `drafting` | Same revision, `pending_review`. |
| `correct` | `drafting`, `pending_review` | Changed content creates a new `drafting` revision, with no review. |
| `approve` | `pending_review` | Same revision, `approved`, with matching authorized human review. |
| `reject` | `pending_review` | Same revision, `rejected`, with matching authorized human review. |
| `cancel` | `drafting`, `pending_review` | Same revision, `cancelled`. |

Approved, rejected, and cancelled candidates are closed to new operations. An
exact retry of an already successful operation can still return its saved result.
Unknown operations and invalid transitions fail with `WorkflowError`.

Submission and approval require nonempty observations with no abstentions. A draft
may retain incomplete or abstained observations for correction or cancellation.
Uncertainty is preserved during review and approval; confidence does not turn a
self-reported observation into a verified clinical fact.
Source and candidate text must pass the documented identifier checks before entry
and on new transitions. Corrections are screened before saving. Failures leave
state and retry records unchanged; invalid drafts never become reviewable.

## Corrections and snapshots

`correct` takes a new `revision_id` and a complete replacement observation list.
Changed content retains the candidate and session IDs, references the current
revision as its parent, increments the revision number, and resets to drafting.
Known revision IDs cannot be reused. The extraction-adapter provenance is retained;
the patient correction is represented by the revision relationship.

An unchanged observation list leaves revision identity and state intact. Supply
one proposed new revision ID per save attempt and reuse it when retrying; it is
only adopted when content changes. A saved replacement list is explicit, not a
patch that silently discards absent fields. Prior revisions remain accessible.

`candidate_intake` returns the current snapshot, and `revision_history` returns
the latest workflow snapshot of each content revision known to this instance.
All returned objects are detached. Changing them, the original constructor input,
or a supplied replacement observation does not mutate the machine's state.

## Reviewer authorization boundary

The trusted application constructs the machine with `authorized_reviewer_id`
after authenticating and authorizing that reviewer for the candidate's session.
The patient can be that reviewer when confirming their own report; confirmation
means the structured proposal accurately represents their report, not that it is
clinically verified. Role policy still needs maintainer agreement before UI/API
integration.

`approve` and `reject` require a validated `HumanReview` whose reviewer ID matches
that configured identity, decision matches the operation, and revision ID matches
the current candidate. A reviewer ID supplied by a browser or an extraction model
cannot establish permission. The application must authorize all access to the
machine, including corrections and cancellations. This module is not an endpoint
or an authentication system, and its constructor must not load untrusted
pre-approved snapshots as authoritative state.

## Stale requests and retries

Every operation requires two keyword arguments:

- `expected_revision_id`: the revision shown to the patient when they acted.
  A new operation targeting a superseded revision fails with `stale_revision`.
- `operation_id`: an opaque UUID identifying one logical request. A retry must
  reuse it with the exact same arguments, including timestamps and proposed IDs.

A successful operation stores its arguments and a detached result in a private
in-memory record. Repeating it returns that original result. Reusing its ID for
different arguments or another operation fails with `operation_id_conflict`.
Failed operations change no state and do not reserve their operation ID.

A delayed successful retry can return an older snapshot after newer work has
occurred. It never rewinds the current candidate. Read `candidate_intake` when the
current snapshot is needed instead of treating a replay result as the latest state.

## Synthetic example

```python
from datetime import datetime, timezone
from uuid import UUID

from datalife_clinical_agents.schemas import (
    CandidateIntakeV1, HumanReview, ReviewStatus, SessionInputV1,
)
from datalife_clinical_agents.state_machine import StateMachine

session_id = UUID(int=1)
revision_id = UUID(int=2)
session = SessionInputV1(
    subject_key="synthetic-subject-001",
    intake_input={"raw_text": "Synthetic report: headache for three days."},
    session_metadata={
        "session_id": session_id, "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
    },
)
draft = CandidateIntakeV1(
    candidate_id=UUID(int=3),
    revision_id=revision_id,
    revision_number=1,
    session_id=session_id,
    extraction_provenance={"adapter_name": "synthetic_fixture", "adapter_version": "1"},
    observations=[{
        "provenance": {"session_id": session_id},
        "value_unit": {"observation_type": "symptom", "symptom": "headache"},
        "uncertainty": {"is_uncertain": True, "abstained": False},
    }],
)
workflow = StateMachine(
    candidate_intake=draft, session_input=session,
    authorized_reviewer_id="synthetic-patient-001",
)
submit_arguments = {
    "operation_id": UUID(int=10), "expected_revision_id": revision_id,
}
pending = workflow.submit_for_review(**submit_arguments)
assert workflow.submit_for_review(**submit_arguments) == pending
assert draft.review_status is ReviewStatus.DRAFT

decision = HumanReview(
    revision_id=revision_id,
    reviewer_id="synthetic-patient-001",
    decision=ReviewStatus.APPROVED,
    reviewed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)
approved = workflow.approve(
    decision, operation_id=UUID(int=11), expected_revision_id=revision_id,
)
assert approved.review_status is ReviewStatus.APPROVED
assert approved.observations[0].uncertainty.is_uncertain is True
```

## Limits and failure behavior

The machine reads no clock and generates no UUIDs. Trusted callers supply those
values once, so identical initial candidates, configuration, and operation inputs
produce identical results. Every transition constructs and validates a complete
new candidate before changing state. Errors are fixed codes without submitted
clinical content or identifiers, and the module performs no logging.

One instance tracks one candidate. Calls must be serialized by its owner; this is
not a transaction across threads or workers. Revision and retry records exist
only for this instance's lifetime, consume memory, and are not restored by creating
a fresh machine from a snapshot. They are not a new audit subsystem. Distributed
concurrency, durable retry storage, permission revocation, and retention policy
belong to a later hosting integration, not this offline reference module.

`validation.py` now applies the typed boundary and text checks. Pending review
means structural readiness and these documented checks passed; it is not proof
of anonymity or clinical accuracy. See [Validation](validation.md) for detection
limits. Approval never triggers serialization or external writes.

The [serializer](serialization.md) explicitly requests `get_approved_candidate`
for the expected current revision and checks the boundaries again. Only an
approval performed by this instance establishes eligibility. Loading a snapshot
that merely claims approval does not, and copying a snapshot or constructing a
fresh machine cannot restore approval authority from an earlier instance.
