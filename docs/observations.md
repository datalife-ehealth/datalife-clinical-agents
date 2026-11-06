# Observation v1

Keep the related input and observation models in `schemas.py` while the contract
is small. Splitting by domain can wait until navigating the file becomes difficult.

`ObservationV1` is a proposal containing four things:

- `schema_version`: the literal string `"1"`.
- `provenance`: a required source-session UUID and `self_reported` origin.
- `value_unit`: one of two explicit observation shapes, shown below.
- `uncertainty`: patient uncertainty, extraction confidence, and abstention.

## Typed values

`value_unit.observation_type` selects the permitted fields. This is a discriminated
union: Pydantic reads that tag and validates the corresponding model.

| Type | Fields | Missing values |
| --- | --- | --- |
| `symptom` | `symptom` text, optional `duration_days` | Missing symptom requires abstention; missing duration remains unknown. |
| `blood_pressure` | Integer `systolic`, integer `diastolic`, `unit: "mmHg"` | Missing either measurement requires abstention. |

Duration must be finite and nonnegative. Blood-pressure values must be positive
integers. These are representation checks, not clinical reference ranges or a
judgment that a measurement is plausible or correct. Values are never inferred or
converted into medical recommendations. Unknown types, units, and fields fail
validation, including when abstaining. Medication and history types are not yet
supported; they need their own typed contracts and tests before use.

Here is an invented observation:

```python
from uuid import UUID

from datalife_clinical_agents.schemas import ObservationV1

observation = ObservationV1(
    provenance={
        "session_id": UUID("00000000-0000-4000-8000-000000000001"),
    },
    value_unit={
        "observation_type": "symptom",
        "symptom": "headache",
        "duration_days": 3.0,
    },
    uncertainty={"is_uncertain": True, "abstained": False},
)

assert observation.uncertainty.confidence_score is None
assert observation.uncertainty.is_uncertain is True
```

## Uncertainty and abstention

`is_uncertain` records whether the patient expressed doubt. `confidence_score` is
optional extraction confidence between 0 and 1; unknown is `None`. It is not
clinical certainty and never overrides patient uncertainty or grants approval.
Both boolean flags must be supplied explicitly.

`abstained=True` requires a nonblank `abstained_reason`. When `abstained=False`, a
reason is forbidden. An abstention may keep partial values, such as a reported
systolic measurement without a diastolic measurement, for later correction.
Abstention can also reflect ambiguity even when all value fields are filled.
It does not imply that the patient expressed doubt; extraction can abstain for
other reasons, including a missing measurement.

## Candidate and workflow boundaries

`CandidateIntakeV1` contains these typed observations and ties them to a specific
candidate revision. It checks that observation provenance session IDs match the
candidate's session ID. Trusted application code must also check that this is the
intake actually being processed. A claimed session UUID or source label is not
proof that the content came from that source. See
[Candidate intake v1](candidate_intake.md) for revision and review rules.

Keep revision identity, parent references, review state, and approval authorization
outside the patient-provided observation fields. A structurally valid observation
is not automatically reviewable, approved, or eligible for ingestion. Later
validation and workflow code must handle abstentions explicitly.

The same privacy and validated-snapshot precautions described in
[Session input v1](session_input.md) apply here: free-text PII screening remains
unimplemented, serialization includes content, and validated instances should not
be modified through unvalidated updates. Free-text symptom and abstention fields
are omitted from normal representations; this does not make arbitrary logging safe.
