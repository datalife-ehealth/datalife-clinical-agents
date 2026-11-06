# Unicode Text Normalization for Policy Matching

## Purpose

The `normalize_for_policy_match()` function creates a deterministic, normalized representation of text for policy matching.

It does not perform clinical decisions, detect personally identifiable information (PII), or modify the original clinical record.

## Transformation Order

The function applies the following operations:

1. Validate that the input is a string.
2. Reject inputs longer than 10,000 characters.
3. Apply Unicode case folding using `casefold()`
4. Apply Unicode NFKC normalization.
5. Remove U+200B (ZERO WIDTH SPACE).
6. Collapse whitespace using `split()` and `" ".join()`.
7. Reject normalized outputs longer than 10,000 characters.
8. Return the normalized text.

## Zero-Width Character Policy

The current implementation removes only `U+200B`.

Other invisible characters, including `U+200C` (ZERO WIDTH NON-JOINER), `U+200D` (ZERO WIDTH JOINER), and `U+FE0F` (VARIATION SELECTOR-16), are not explicitly removed.

This narrow policy avoids indiscriminately deleting characters that may have linguistic or presentation significance.

## Safety and Limitations

- Uses only the Python standard library.
- Raises `TypeError` for non-string inputs.
- Raises `ValueError` when input or output exceeds the configured limit.
- Error messages do not include the input text.
- NFKC normalization can change compatibility distinctions, so the normalized representation must not replace the original clinical text.
- The output limit is checked after normalization; intermediate allocations are not separately bounded.
- Normalization uses a single `casefold()` → NFKC pass for predictable runtime and bounded processing. Certain Unicode code points (such as U+037A and U+03F9) may require multiple passes to stabilize, so universal idempotence is not guaranteed.

## Testing

Run the unit tests from the repository root:

```bash
python -m unittest discover -s tests -p "test_text_policy_normalization.py" -v
```

Synthetic boundary cases are stored in `tests/fixtures/unicode_boundary_cases.json`.
