"""Compatibility import for the packaged runtime normalization utility."""

from datalife_clinical_agents.text_policy_normalization import (
    MAX_INPUT_LENGTH, MAX_OUTPUT_LENGTH, normalize_for_policy_match,
)

__all__ = ["MAX_INPUT_LENGTH", "MAX_OUTPUT_LENGTH", "normalize_for_policy_match"]
