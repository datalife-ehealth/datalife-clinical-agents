# Ingestion envelope v1

`IngestionEnvelopeV1` validates the outer JSON ingestion request shape. It does not
create a payload from a candidate, approve observations, or send an HTTP request.

The contract was checked against the core
[`IngestRequest`](https://github.com/datalife-ehealth/datalife-datalake-core/blob/8a4e42e70810cc58907da27ca85ed7dafc44902e/src/api/routes/ingestion.py)
and its
[payload parser](https://github.com/datalife-ehealth/datalife-datalake-core/blob/f830bcfa0917764491fef0d392faf71158271683/src/services/parsing.py).

## Fields

| Field | Rule |
| --- | --- |
| `subject_key` | Required strict string, 4 to 64 characters, not whitespace-only. |
| `kind` | Literal `"json"`, supplied by default. |
| `media_type` | Literal `"application/json"`, supplied by default. |
| `body` | Required strict string containing one JSON object. |

These are the only permitted outer fields. There is no extra outer
`schema_version`: the `V1` class names this envelope contract, while intake content
versioning belongs inside `body`. There are no `body_dict` or `body_serialized`
fields. Keeping one body avoids having two representations that can disagree.

The core accepts JSON objects and arrays; this intake envelope deliberately
requires an object. It rejects malformed JSON, duplicate keys at any depth,
NaN/Infinity constants, numbers that overflow to infinity, and body text that
cannot be encoded as UTF-8. Duplicate keys are rejected instead of silently
replacing an earlier value. Validation preserves the original body string,
including whitespace, because the core hashes that exact text.

## Constructing the outer shape

`json.dumps` serializes a Python value into a JSON string. It must run when that
value exists, rather than during class definition. For example:

```python
import json

from datalife_clinical_agents.schemas import IngestionEnvelopeV1

# A structural example only, not an approved or ingestible intake candidate.
body_text = json.dumps(
    {"schema_version": "1", "observations": []},
    allow_nan=False,
)
envelope = IngestionEnvelopeV1(
    subject_key="synthetic-subject-001",
    body=body_text,
)

payload = envelope.model_dump()
assert set(payload) == {"subject_key", "kind", "media_type", "body"}
assert isinstance(payload["body"], str)
```

Serializing the envelope itself escapes the JSON string in `body`. This is
expected: the outer request is a JSON object containing an inner JSON document
as a string, as required by the core API.

## Remaining boundaries

This model validates the transport shape, not the clinical content. A JSON object
such as `{}` may pass these checks without containing a usable intake. Inner
observation types, unknown privileged fields within the body, subject/session
binding, PII screening, and approval of the exact current revision must be checked
by the later Phase 4 serializer and boundary validation. The serializer must build
the body from typed candidate data, rather than accept arbitrary dictionaries as
approved content.

The core also imposes configurable body-size, nesting-depth, and node-count limits.
Those resource limits are not implemented by this schema; valid syntax alone is
not a claim that the core will accept a payload. Consistent local resource limits
remain part of the Phase 4 boundary work.

The body and subject key are omitted from normal model representations. Model
dumps and structured validation errors can still contain submitted data and must
not be logged indiscriminately. Treat instances as validated snapshots and
revalidate changed data; unvalidated updates are not a validation boundary.
