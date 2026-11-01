import unicodedata

MAX_INPUT_LENGTH = 10_000
MAX_OUTPUT_LENGTH = 10_000


def normalize_for_policy_match(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("Text must be a string")
    if len(text) > MAX_INPUT_LENGTH:
        raise ValueError("Input text exceeds maximum length")
    casefolded_text = text.casefold()
    nfkc_text = unicodedata.normalize("NFKC", casefolded_text)
    normalized_text = nfkc_text.replace("\u200b", "")
    words = normalized_text.split()
    normalized_text = " ".join(words)
    if len(normalized_text) > MAX_OUTPUT_LENGTH:
        raise ValueError("Normalized text exceeds maximum length")
    return normalized_text
