# Session input v1

`SessionInputV1` describes a submitted report before extraction or human review.
It requires an opaque subject key, meaningful intake text, and session metadata.
An unfinished draft is not a valid submission. Missing clinical details within
otherwise meaningful text remain valid input; this schema does not judge clinical
completeness or certainty.

All models inherit `Arguments`, which enables strict types and rejects unknown
fields. For example, an `approved` field fails validation at every level; this
input contract cannot express an approval or a privileged action.

## Creating a session

Trusted application code supplies the subject key and creates the session ID and
timezone-aware timestamp once. Reuse those values on retries; validation itself
does not create IDs or read the clock.

```python
from datetime import datetime, timezone
from uuid import uuid4

from datalife_clinical_agents.schemas import SessionInputV1

# Invented data only. A real subject key must come from the patient client.
session = SessionInputV1(
    subject_key="synthetic-subject-001",
    intake_input={"raw_text": "I have had a headache for three days."},
    session_metadata={
        "session_id": uuid4(),
        "timestamp": datetime.now(timezone.utc),
    },
)

retry = SessionInputV1.model_validate_json(session.model_dump_json())
assert retry == session
```

Explicit metadata makes stable retries possible. It does not yet implement
operation deduplication, verify who created the metadata, or authorize review.
Those checks belong in trusted workflow code.

## Field rules

- `schema_version` defaults to the literal string `"1"` and is included in normal
  serialization. Other versions fail validation. Versioning is independent of the
  package version. Breaking contract changes should introduce a new version.
- `subject_key` is required, is not generated here, and must be 4 to 64 characters,
  matching the core ingestion request. Whitespace-only keys are also rejected.
  A valid string is not proof that it is an authorized, nonidentifying subject key.
- `intake_input.raw_text` is required and rejects empty, whitespace-only, and
  non-string values. The original text is preserved, including whitespace.
- `modality` defaults to `Modality.TEXT`. `Modality.AUDIO` means an existing audio
  transcript; this package does not process audio files.
- `session_metadata.session_id` is a required UUID.
- `session_metadata.timestamp` is required and must include a timezone.

Strict Python construction uses typed objects: a `UUID`, an aware `datetime`, and
a `Modality` enum when overriding the default modality. Use
`SessionInputV1.model_validate_json(...)` for JSON: UUIDs, timestamps, and modality
values necessarily have string representations in that format. Passing those
JSON strings through `model_validate(...)` is not the same operation.

The core constraint is defined in
[`IngestRequest`](https://github.com/datalife-ehealth/datalife-datalake-core/blob/main/src/api/routes/ingestion.py).
No core endpoint is called during validation or tests.

## Privacy and remaining boundaries

Successful schema validation checks structure and types. It does not scan free
text for direct identifiers or make the report safe for central services. The
privacy gate, input-size limits, extraction outcomes, revisions, and authorized
human review still need implementation in later steps.

Raw text and subject keys are omitted from normal model representations. Pydantic
error strings hide rejected input values, but `ValidationError.errors()` can still
contain submitted values, and model serialization includes the report. Do not log
raw reports, model dumps, or complete validation errors. This module does not log
or send data.

Treat validated instances as input snapshots. Revalidate changed data instead of
using attribute assignment, `model_construct`, or unvalidated `model_copy` updates
as a validation boundary.
