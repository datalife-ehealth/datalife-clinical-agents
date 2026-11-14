# Candidate intake envelope v1

`CandidateIntakeEnvelopeV1` validates the outer request shape for candidate-intake JSON.
It does not approve observations or send an HTTP request.

The contract was checked against the core
[`IngestRequest`](https://github.com/datalife-ehealth/datalife-datalake-core/blob/main/src/api/routes/ingestion.py)
and its
[payload parser](https://github.com/datalife-ehealth/datalife-datalake-core/blob/main/src/services/parsing.py).

## Relationship to core

| Field | Core `IngestRequest` | Local `CandidateIntakeEnvelopeV1` |
| --- | --- | --- |
| `subject_key` | String, 4 to 64 characters. | Canonical UUIDv4 string, 36 characters. |
| `kind` | `json`, `xml`, or `dicom`. | Only `json`. |
| `media_type` | String, default `application/octet-stream`. | Only `application/json`. |
| `body` | Nonempty string; content parsing is a separate core responsibility. | String already checked to contain one valid JSON object. |

This contract intentionally supports only the candidate JSON subset of core's
`IngestRequest`; XML and DICOM are outside scope. Core validation still applies.
`V1` versions this local envelope contract, not the core API.

The previous name `IngestionEnvelopeV1` has been replaced by
`CandidateIntakeEnvelopeV1`; update imports and type annotations. The serialized
outer fields are unchanged.

## Fields

| Field | Rule |
| --- | --- |
| `subject_key` | Required canonical lowercase, hyphenated UUIDv4 string (36 characters). |
| `kind` | Literal `"json"`, supplied by default. |
| `media_type` | Literal `"application/json"`, supplied by default. |
| `body` | Required strict string containing one JSON object. |

These are the only permitted outer fields. There is no extra outer
`schema_version`: the `V1` class names this envelope contract, while intake content
versioning belongs inside `body`. There are no `body_dict` or `body_serialized`
fields.

The subject-key format is a local intake restriction within the core's broader
string contract. `SessionInputV1` holds a typed UUIDv4; the serializer converts
that bound key to a string. Direct envelope construction also rejects names,
emails, phone numbers, other UUID versions, and noncanonical UUID spellings.
The key must be randomly generated and reused by the patient client, with its
identity mapping kept on the patient-controlled device. Format validation alone
does not prove ownership or that the UUID was generated randomly.

The core accepts JSON objects and arrays; this intake envelope deliberately
requires an object. It rejects malformed JSON, duplicate keys at any depth,
NaN/Infinity constants, numbers that overflow to infinity, and body text that
cannot be encoded as UTF-8. Duplicate keys are rejected instead of silently
replacing an earlier value. Validation preserves the original body string,
including whitespace, because the core hashes that exact text.

## Structural example

```python
import json

from datalife_clinical_agents.schemas import CandidateIntakeEnvelopeV1

# A structural example only, not an approved or ingestible intake candidate.
body_text = json.dumps(
    {"schema_version": "1", "observations": []},
    allow_nan=False,
)
envelope = CandidateIntakeEnvelopeV1(
    subject_key="b4c3c202-31f4-4f10-8b49-0d067a2fc1e8",
    body=body_text,
)

payload = envelope.model_dump()
assert set(payload) == {"subject_key", "kind", "media_type", "body"}
assert isinstance(payload["body"], str)
```

`body` remains a JSON string inside the outer request, not a nested dictionary.

## Boundary enforcement

This model validates the transport shape, not the clinical content. A JSON object
such as `{}` may pass these checks without containing a usable intake. Inner
observation types, unknown privileged fields within the body, subject/session
binding, PII screening, and approval of the exact current revision must be checked
by the [serializer](serialization.md) and shared [validation](validation.md).
The serializer builds the body only from the workflow's current approved typed
candidate; it does not accept arbitrary dictionaries as approved content.

The core also imposes configurable body-size, nesting-depth, and node-count limits.
The standalone schema checks syntax; the `validate_ingestion_envelope` boundary
function additionally enforces those resource limits. The serializer always uses
that boundary function. A structurally valid envelope alone is not evidence of
approval, authorization, or acceptance by a differently configured core instance.

The body and subject key are omitted from normal model representations. Model
dumps and structured validation errors can still contain submitted data and must
not be logged indiscriminately. Treat instances as validated snapshots and
revalidate changed data; unvalidated updates are not a validation boundary.
