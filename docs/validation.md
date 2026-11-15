# Text boundary rejection

`validation.py` provides offline boundary functions and a small text checker. It
uses the package's existing Pydantic dependency and the standard library, with no
NLP model, additional dependencies, network calls, or logging. It detects specific
recognizable identifier forms; it does not guarantee anonymity.

## Safe results and rejection

`PIIBoundaryChecker.check_text(text)` returns a `BoundaryResult`. Its immutable
`findings` tuple contains one `Finding` per detected category, in a fixed order.
Each finding contains only a category and the fixed path `"text"`. There is no raw
text, matched value, character offset, or caller-controlled field path in a result.

`result.has_violations` indicates that the text must be rejected under these
rules. `require_text(text)` raises `BoundaryValidationError` with the fixed message
`text_boundary_rejected` when violations exist. Neither method redacts or rewrites
the report. The UI should ask the patient to correct rejected input explicitly.

```python
from datalife_clinical_agents.validation import (
    BoundaryCategory, PIIBoundaryChecker,
)

checker = PIIBoundaryChecker()
result = checker.check_text("Contact synthetic.patient@example.com.")
assert result.has_violations
assert result.findings[0].category is BoundaryCategory.EMAIL
assert result.findings[0].path == "text"

checker.require_text("Blood pressure was 145/90 mmHg.")
```

The module does not retain the report on the checker or result. The caller still
has the original input and must not log it or persist rejected content. Safe
results do not make the surrounding application's logging or retention safe.

## Supported rules

The baseline value patterns are adapted from the core's MIT-licensed
[`services/pii.py`](https://github.com/datalife-ehealth/datalife-datalake-core/blob/main/src/services/pii.py),
reviewed at file blob `7bf63b079800d62363e58a5db5cb980c38ec25ec`. They are maintained
locally rather than importing the core service or calling it over the network.
Synthetic compatibility examples cover the shared formats and clinical exclusions.
The local email rule additionally handles a sentence-ending period after the
address, which the reviewed core pattern can miss.

| Category | Recognized forms |
| --- | --- |
| `email` | Bounded conventional email syntax. |
| `government_id` | Formatted CPF (`000.123.456-00`) and SSN (`000-12-3456`) shapes. |
| `phone` | Formatted international, parenthesized area code, or North American 3-3-4 forms with at least seven digits. |
| `patient_name` | Explicit cues such as `my name is`, `patient name:`, `full name:`, or a standalone `Name:` label. |
| `medical_record_number` | Explicit `MRN` or `Medical Record Number` labels followed by `:` or `#`, case-insensitive. |
| `invalid_input` | Non-string, blank, or non-UTF-8-encodable input. |
| `input_too_large` | Input exceeding the configured UTF-8 byte limit. |

Identifier checks reject recognizable forms even if their check digits or actual
assignments are invalid. Phone checks retain the core's unit guards so numeric
clinical sequences followed by units are not treated as phone numbers. They are
conservative format checks, not complete international phone validation.

The explicit-name rule is an intake-specific addition to the shared core value
patterns. It detects identity cues without trying to parse arbitrary personal
names. It may reject a phrase containing a cue even when the patient did not
actually supply a name. It deliberately avoids matching `symptom name: headache`.

The MRN rule rejects an explicit label, even when its value is missing or marked
unavailable. It does not guess MRNs from unlabeled numbers or ordinary mentions
without `:` or `#`; clinical measurements are not treated as MRNs by numeric shape.

ZIP/city/gender/IP uniqueness heuristics, passport rules, credit-card rules, and
general name recognition are not implemented. The subject key is restricted to UUIDv4 by the
session schema and to a canonical UUIDv4 string by the envelope schema, rather
than relying on incomplete name detection. The patient client must generate it
randomly and preserve its identity mapping locally. UUID session/revision IDs
are not patient report text. Adapter and reviewer string metadata are screened because they
appear inside the clinical JSON body; they must not contain recognizable direct
identifiers such as an email address.

The default limit is 16,384 UTF-8 bytes per checked text, configurable through
`PIIBoundaryChecker(max_text_bytes=...)`. This is a local intake-text policy,
independent of the core's whole-body size and structural limits. Oversized input
is rejected before regex scanning; invalid input never produces a clean result.

## Unicode matching

Before pattern matching, the shared checker uses `normalize_for_policy_match()`
from the installed package: casefold, NFKC, selected Cyrillic-to-Latin lookalike
mapping, removal of U+200B/U+200C/U+200D/U+2060/U+FEFF, and whitespace
collapse. This catches zero-width-space interruptions and compatibility forms
such as full-width email punctuation. The original text is also checked for
line-based name cues. Both original and normalized text must fit the configured
UTF-8 byte budget; invalid or normalized-empty text is rejected.

Supported lookalike handling covers full-width ASCII through NFKC and the mapped
Cyrillic letters `а е о р с х у і ј ѕ н к` (including their uppercase forms).
Generalized Unicode confusables, including unmapped Greek lookalikes, remain
outside scope.

Normalization affects only the matching copy. Accepted clinical text is preserved
in the models and output. Workflow entry, review, and serialization use this same
checker. This does not recognize bare names, resolve arbitrary cross-alphabet
lookalikes, or remove every invisible Unicode character. No finding is not proof
of anonymization.

## Direct-name limitation

Names and identity mappings remain on the patient-controlled device. This package
accepts no `known_names` list and implements no frontend identity check.
Explicit-cue rules miss prose such as the synthetic sentence
`Mara Quill reports a headache.` A result without findings is not proof of anonymity.

The direct-name requirement in [RFC #1](https://github.com/datalife-ehealth/datalife-clinical-agents/issues/1)
remains an open limitation. This research/reference package must not be represented
or relied upon as a comprehensive PII screen for production clinical ingestion.
Generalized NER is tracked in [#10](https://github.com/datalife-ehealth/datalife-clinical-agents/issues/10).
No NLP models or capitalization heuristics are part of this boundary layer.

## Shared boundary functions

Use these functions at application boundaries rather than treating a standalone
schema constructor as the complete privacy check:

| Function | Checks |
| --- | --- |
| `validate_session_input` | Strict session schema, resource bounds, and source report text. Call before any future extraction adapter. |
| `validate_observation` | Strict typed observation, resource bounds, symptom text, and any abstention reason. |
| `validate_candidate` | Existing revision/review schema rules, source-session binding, source text, all observation text, adapter identity strings, and any reviewer ID. |
| `validate_ingestion_envelope` | Exact transport contract, bounded JSON parsing, and core-compatible body resource limits. Does not establish approval. |

The functions accept existing models or Python input dictionaries and return
revalidated models. Strict Python-mode UUID, datetime, and enum requirements still
apply. There is no new HTTP parsing endpoint. Unexpected fields, prohibited identity
fields such as `name`, unknown observation types, and privileged action fields fail
through the schemas' allowlists, not by guessing meaning from arbitrary text.
The workflow has only explicit operations; prompt text cannot grant privileges.

The state machine requires a source `session_input` at construction and checks
its ID against the candidate. Entry, corrections, and new transitions run these
checks; submission/approval failures never change state. The serializer checks
the current authorized approval separately and then reruns source and candidate
validation. A retry returns only a detached prior result; it does not grant
permission to serialize that snapshot as current output.

## Resource bounds

`ValidationLimits` is immutable configuration shared by the workflow and serializer:

| Setting | Default |
| --- | --- |
| Per-text UTF-8 bytes | 16,384 |
| JSON body UTF-8 bytes | 1,000,000 |
| Maximum depth | 64 |
| Maximum value/container nodes | 10,000 |

The last three defaults match the inspected core
[`Settings`](https://github.com/datalife-ehealth/datalife-datalake-core/blob/main/src/core/config.py),
file blob `6212794c64704f7a00c840069abf7ad5029d2903`. Configured deployments must
keep local limits compatible with the target core's configured limits.

An iterative precheck bounds Python inputs before schema cloning, including cyclic
or excessively wide inputs. Limits are checked again after defaults are populated.
Values and containers count as nodes; keys do not. The root is depth 1, and scalar
leaves count toward depth, matching core JSON measurement. Aggregate string/key
bytes are bounded before serialization. The serializer enforces the exact body
byte budget while encoding, including JSON punctuation/escaping overhead.

Envelope validation bounds body size and bracket nesting before recursive JSON
decoding, then checks decoded depth, nodes, and UTF-8 validity. It also catches lone
surrogates introduced by JSON escapes. The envelope schema rejects duplicate keys,
nonfinite numbers, and unsupported roots. All errors crossing these boundaries use
fixed messages without raw values or parser details. PII rejection remains separate
from review readiness and authorization.
