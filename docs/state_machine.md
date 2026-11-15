# Deterministic intake state machine

`state_machine.py` operates on one candidate in memory. The schemas describe valid
snapshots; the machine checks which operation may produce the next snapshot.
It performs no extraction, network calls, persistence, or clinical decisions.
Construction requires `session_input` as well as the candidate and authorized
reviewer. The validated source session is bound to the candidate's session ID;
its opaque subject key is later used by the serializer.

Inputs and outputs are strict Pydantic snapshots with instance revalidation.
Transitions validate the complete proposed update before changing state or retry
records. Returned snapshots are detached; unvalidated copies are not a validation
boundary.

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

For a complete approval and serialization example, see [Serialization](serialization.md#synthetic-example).

## Limits and failure behavior

Each instance has two configurable capacities, supplied as constructor keyword
arguments. Both must be positive integers (booleans are rejected):

| Setting | Default | What counts |
| --- | --- | --- |
| `max_revisions` | 100 | Initial candidate counts as one; each changed correction adds one. |
| `max_operations` | 1,000 | Each successful new operation ID, including unchanged saves. |

These are local reference defaults, not core API limits or measured RAM budgets.

When a new request would exceed a capacity, it fails with
`revision_capacity_reached` or `operation_capacity_reached`. Current state,
approval eligibility, history, and retry receipts remain unchanged. Failed
requests do not consume capacity or reserve an operation ID. An unchanged save
does not create a revision, but its new operation receipt still consumes a slot.

No entries are evicted and there is no TTL: exact retries remain available even
at capacity, including delayed retries for older revisions. Reusing a recorded
operation ID for different arguments still fails. At the revision limit,
submission, approval, rejection, cancellation, and unchanged saves can continue
if operation slots remain. At the operation limit, all new operations stop;
current snapshots and already-authorized serialization remain available.
The hosting application must budget slots for editing and review and handle
capacity errors explicitly. Recreating a machine loses retry history and does
not restore approval authority.

These count limits combine with the existing per-payload resource limits to
bound retained history and receipts for one instance. They are not an exact RAM
budget or a limit on how many instances a hosting application may keep alive.

The machine reads no clock and generates no UUIDs. Trusted callers supply those
values once, so identical initial candidates, configuration, and operation inputs
produce identical results. Every transition constructs and validates a complete
new candidate before changing state. Errors are fixed codes without submitted
clinical content or identifiers, and the module performs no logging.

One instance tracks one candidate. Calls must be serialized by its owner; this is
not a transaction across threads or workers. Revision and retry records exist
only for this instance's lifetime and are not restored from a snapshot.
Distributed concurrency, durable retries, permission revocation, and instance
lifecycle management remain hosting responsibilities.

`validation.py` applies the typed boundary and text checks. Pending review
means structural readiness and these documented checks passed; it is not proof
of anonymity or clinical accuracy. See [Validation](validation.md) for detection
limits. Approval never triggers serialization or external writes.

The [serializer](serialization.md) explicitly requests `get_approved_candidate`
for the expected current revision and checks the boundaries again. Only an
approval performed by this instance establishes eligibility. Loading a snapshot
that merely claims approval does not, and copying a snapshot or constructing a
fresh machine cannot restore approval authority from an earlier instance.
