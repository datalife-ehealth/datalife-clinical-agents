# Candidate intake v1

`CandidateIntakeV1` describes one candidate revision and its review state. Trusted
application code assembles this model from validated observation proposals.
Patient input and extraction adapters must not supply the candidate's privileged
IDs, revision metadata, review state, or human-review record.

## Extraction provenance

`extraction_provenance` is required and records which adapter produced the
structured observations. Its `adapter_name` and `adapter_version` are required
strict strings; empty and whitespace-only values are rejected. Unexpected fields
are rejected too. Trusted application code supplies these values from the adapter
it actually used, rather than accepting them from patient input or model output.
This metadata does not prove extraction accuracy or grant approval.

Observation provenance records the self-reported origin and source session.
Extraction provenance instead identifies the software that performed extraction.

## Identity and corrections

These fields serve different purposes:

- `candidate_id`: stable identity across all corrections of one candidate.
- `revision_id`: unique identity of one content revision.
- `revision_number`: positive integer starting at 1.
- `parent_revision_id`: previous revision ID; absent for revision 1 and required
  for subsequent revisions. A revision cannot be its own parent.
- `session_id`: source intake session; must match every observation's provenance.

The schema checks one snapshot. It cannot establish that a parent actually
exists, that it belongs to this candidate and session, or that the number is
exactly one greater than the parent's. The [state machine](state_machine.md) manages
the parent relationship, prevents reuse of known revision IDs, increments the
number, and resets changed candidates to drafting with no inherited review.
Reusing an approved revision ID for changed content is forbidden by the workflow
contract; the schema alone cannot detect that reuse.

## Review consistency

`review_status` defaults to `ReviewStatus.DRAFT`. Strict Python construction uses
the enum; JSON validation accepts its documented string values.

| State | Observations | Human-review record |
| --- | --- | --- |
| `drafting` | May be empty or include abstentions. | Must be absent. |
| `pending_review` | Nonempty; no abstained observations. | Must be absent. |
| `approved` | Nonempty; no abstained observations. | Required, with matching approval and revision ID. |
| `rejected` | Retained, including any unresolved content. | Required, with matching rejection and revision ID. |
| `cancelled` | Retained, including any unresolved content. | Must be absent. |

These are snapshot consistency rules, not permission to transition between states.
An abstained observation must be corrected explicitly before review; it must not
be silently discarded to pass validation. Patient uncertainty may remain during
review and approval, and is preserved rather than converted into certainty.

`HumanReview` records the exact revision ID, an opaque reviewer ID, a decision,
and a timezone-aware decision timestamp. Its fields document the required human
decision; this is not a separate audit system. A matching record is necessary but
does not prove that a human acted or that the reviewer was authorized. Only
trusted workflow code can establish that. An externally supplied `approved`
snapshot must never grant ingestion rights by itself.

## Synthetic draft example

```python
from uuid import UUID

from datalife_clinical_agents.schemas import CandidateIntakeV1

session_id = UUID("00000000-0000-4000-8000-000000000001")
candidate = CandidateIntakeV1(
    candidate_id=UUID("00000000-0000-4000-8000-000000000002"),
    revision_id=UUID("00000000-0000-4000-8000-000000000003"),
    revision_number=1,
    session_id=session_id,
    extraction_provenance={
        "adapter_name": "synthetic_fixture",
        "adapter_version": "1",
    },
    observations=[{
        "provenance": {"session_id": session_id},
        "value_unit": {"observation_type": "symptom", "symptom": "headache"},
        "uncertainty": {"is_uncertain": True, "abstained": False},
    }],
)

assert candidate.schema_version == "1"
assert candidate.human_review is None
```

Repeat validation with the same supplied IDs preserves identity; the state
machine also supports operation retries within one instance's lifetime.
Models remain validated snapshots: revalidate
changed data instead of relying on attribute assignment or unvalidated copies.
Serialization includes observation content and review metadata and is not safe
to log. No schema performs network writes or grants review authorization.

The outer ingestion-envelope schema is documented in
[Ingestion envelope v1](ingestion_envelope.md). Building its body from an approved
candidate remains Phase 4 work.
