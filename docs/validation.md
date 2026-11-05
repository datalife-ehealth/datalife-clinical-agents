# Text boundary rejection

`validation.py` provides a small offline text checker. It has no NLP model, third-party
dependencies, network calls, import-time initialization, or logging. It detects
specific recognizable identifier forms; it does not guarantee anonymity.

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

ZIP/city/gender/IP uniqueness heuristics, passport rules, credit-card rules, and
general name recognition are not implemented. Unsupported categories are not
listed as if they were detectors. Opaque subject/session/reviewer IDs are handled
by their trusted contracts and must not be passed through this free-text scanner
as if every identifier were clinical report content.

The default limit is 16,384 UTF-8 bytes per checked text, configurable through
`PIIBoundaryChecker(max_text_bytes=...)`. This is a local intake-text policy,
independent of the core's whole-body size and structural limits. Oversized input
is rejected before regex scanning; invalid input never produces a clean result.

## Patient names remain on the patient device

A separate patient-name field may support an additional local frontend check:
the client can compare its locally held name with the report and ask the patient
to remove identifying text before submission. This is an option for later UI
work, not an implemented feature in this Python module.

Do not add that name or a `known_names` list to `SessionInputV1`, send it to a
central checker, put it in logs, or maintain a shared name glossary. Names and
identity mappings belong on the patient-controlled device. Any UI correction
must be explicit rather than silently deleting text from the patient's report.

Matching a supplied name can miss nicknames, spelling changes, and names of other
people. The backend explicit-cue rule also misses bare names, such as the invented
sentence `Mara Quill reports a headache.` A result without findings means only
that none of these documented rules matched; it is not permission to send arbitrary
free text to central services.

## Remaining integration

This step implements the text-checking primitive and its tests. It is not yet
connected to state transitions, session/extraction intake, or the approved-candidate
serializer. Full boundary validation still needs to reject unsupported fields and
privileged actions through the typed contracts, select every relevant free-text
field for scanning, enforce payload limits, and run at the required workflow
boundaries. PII rejection is separate from review readiness and authorization.
