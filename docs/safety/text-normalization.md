# Unicode Text Normalization for Policy Matching

## Purpose

The `normalize_for_policy_match()` function creates a deterministic, normalized representation of text for policy matching.

Its implementation lives in `src/datalife_clinical_agents/text_policy_normalization.py`.
The existing `tools.text_policy_normalization` import re-exports the same function.
Install the package with `python -m pip install -e .` before running the tools tests.
The runtime privacy checker calls this implementation before matching identifiers.

It does not perform clinical decisions, detect personally identifiable information (PII), or modify the original clinical record.

## Transformation Order

The function applies the following operations:

1. Validate that the input is a string.
2. Reject inputs longer than `max_input_length` (default 10,000 characters).
3. Apply Unicode case folding using `casefold()`
4. Apply Unicode NFKC normalization.
5. Map selected Cyrillic lookalikes to Latin characters.
6. Remove U+200B, U+200C, U+200D, U+2060, and U+FEFF from the matching copy.
7. Collapse whitespace using `split()` and `" ".join()`.
8. Reject normalized outputs longer than `max_output_length` (default 10,000 characters).
9. Return the normalized text.

## Selected lookalikes

NFKC handles full-width ASCII. The explicit mapping covers Cyrillic `а е о р с х у і ј ѕ н к` to Latin
`a e o p c x y i j s h k`. Case folding handles their uppercase forms before
translation; NFKC can also reveal mapped characters from compatibility forms.
Generalized confusables and unmapped Greek lookalikes are outside scope. The
mapping affects only the matching copy, never clinical records.

## Zero-Width Character Policy

Matching removes `U+200B` (ZERO WIDTH SPACE), `U+200C` (ZERO WIDTH NON-JOINER),
`U+200D` (ZERO WIDTH JOINER), `U+2060` (WORD JOINER), and `U+FEFF` (BOM).
This prevents these characters from interrupting identifier patterns. Original
clinical text is preserved. Other characters, such as `U+FE0F` (VARIATION
SELECTOR-16), are not stripped; this is an explicit list, not general removal
of Unicode format characters.

## Safety and Limitations

- Uses only the Python standard library.
- Raises `TypeError` for non-string inputs.
- Raises `ValueError` when input or output exceeds the configured limit.
- Limits must be positive integers; invalid configuration raises `ValueError`.
- Error messages do not include the input text.
- NFKC normalization can change compatibility distinctions, so the normalized representation must not replace the original clinical text.
- The output limit is checked after normalization; intermediate allocations are not separately bounded.
- The runtime checker supplies its configured text limit and checks UTF-8 bytes both before and after normalization. It preserves the original clinical text and rejects detected identifiers rather than redacting them.
- NFKC handles compatibility forms such as full-width punctuation, but does not resolve arbitrary cross-alphabet lookalikes or detect personal names by itself.
- Normalization uses a single `casefold()` → NFKC pass for predictable runtime and bounded processing. Certain Unicode code points (such as U+037A and U+03F9) may require multiple passes to stabilize, so universal idempotence is not guaranteed.

## Testing

Run the unit tests from the repository root:

```bash
python -m unittest discover -s tests -p "test_text_policy_normalization.py" -v
```

Synthetic boundary cases are stored in `tests/fixtures/unicode_boundary_cases.json`.
