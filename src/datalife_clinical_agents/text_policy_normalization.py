"""Create a bounded matching copy; never replace the original clinical text."""

import unicodedata

MAX_INPUT_LENGTH = 10_000
MAX_OUTPUT_LENGTH = 10_000

# Strip only these specified format characters from the matching copy.
INVISIBLE_FORMAT_MAP = str.maketrans("", "", "\u200b\u200c\u200d\u2060\ufeff")

# Selected Cyrillic lookalikes for policy matching, after casefold and NFKC.
# This is a limited allowlist, not a complete Unicode confusable mapping.
HOMOGLYPH_MAP = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x",
    "у": "y", "і": "i", "ј": "j", "ѕ": "s", "н": "h", "к": "k",
})


def normalize_for_policy_match(
    text: str, *, max_input_length: int = MAX_INPUT_LENGTH,
    max_output_length: int = MAX_OUTPUT_LENGTH,
) -> str:
    """Casefold, apply NFKC, map selected lookalikes, and normalize spacing.

    Limits count characters. Callers enforcing a byte budget must also check
    UTF-8 size before and after this transformation. This does not resolve
    arbitrary cross-alphabet lookalikes.
    """
    if any(type(limit) is not int or limit < 1
           for limit in (max_input_length, max_output_length)):
        raise ValueError("Normalization limits must be positive integers")
    if not isinstance(text, str):
        raise TypeError("Text must be a string")
    if len(text) > max_input_length:
        raise ValueError("Input text exceeds maximum length")

    # Normalize first: uppercase and compatibility forms can reveal map entries.
    normalized_text = unicodedata.normalize("NFKC", text.casefold())
    normalized_text = normalized_text.translate(HOMOGLYPH_MAP)
    normalized_text = normalized_text.translate(INVISIBLE_FORMAT_MAP)
    normalized_text = " ".join(normalized_text.split())

    if len(normalized_text) > max_output_length:
        raise ValueError("Normalized text exceeds maximum length")

    return normalized_text
