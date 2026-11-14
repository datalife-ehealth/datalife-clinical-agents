"""Synthetic identifier examples and clinical false-positive regressions."""

import json
from dataclasses import asdict

import pytest

from datalife_clinical_agents.validation import (
    BoundaryCategory,
    BoundaryValidationError,
    PIIBoundaryChecker,
)


@pytest.fixture
def checker():
    return PIIBoundaryChecker()


# Recognizable forms aligned with the core policy, not real patient records.
@pytest.mark.parametrize("text,category", [
    ("Email: synthetic.patient@example.com", BoundaryCategory.EMAIL),
    ("Contact synthetic.patient@example.com.", BoundaryCategory.EMAIL),
    ("Contact synthetic.patient@sub.example.com.", BoundaryCategory.EMAIL),
    ("Contact SYNTHETIC+TEST@EXAMPLE.ORG", BoundaryCategory.EMAIL),
    ("CPF: 000.123.456-00", BoundaryCategory.GOVERNMENT_ID),
    ("SSN: 000-12-3456", BoundaryCategory.GOVERNMENT_ID),
    ("Phone: 202-555-0198", BoundaryCategory.PHONE),
    ("Phone: 202 555 0198", BoundaryCategory.PHONE),
    ("Phone: +1 (202) 555-0198", BoundaryCategory.PHONE),
    ("Phone: (202) 555-0198", BoundaryCategory.PHONE),
    ("Phone: +44 7700 900123", BoundaryCategory.PHONE),
    ("Phone: +55 11 90000-0000", BoundaryCategory.PHONE),
    ("Phone: +33 6 00 00 00 00", BoundaryCategory.PHONE),
])
def test_rejects_core_aligned_identifier_forms(checker, text, category):
    result = checker.check_text(text)
    assert result.has_violations
    assert category in {finding.category for finding in result.findings}
    assert all(finding.path == "text" for finding in result.findings)


@pytest.mark.parametrize("text", [
    "My name is Mara Quill. I have a headache.",
    "MY FULL NAME IS Mara Quill.",
    "Name: Mara Quill", "name = Mara Quill",
    "I have a headache. Name: Mara Quill",
    "Patient name: Mara Quill", "Full name=Mara Quill",
    "Synthetic report\nName: Mara Quill",
])
def test_rejects_explicit_name_cues_without_a_name_glossary(checker, text):
    assert BoundaryCategory.PATIENT_NAME in {
        finding.category for finding in checker.check_text(text).findings
    }


@pytest.mark.parametrize("text", [
    "MRN: 00012345", "MRN#00012345", "mrn # SYNTHETIC-A12",
    "Medical Record Number: SYNTHETIC-0001",
    "medical record number # 00012345",
    "Report\nMRN : SYNTHETIC-A12", "Medical\nRecord Number: 00012345",
    "MR\ufeffN: 00012345", "\uff2d\uff32\uff2e\uff1a 00012345",
    "MRN:",  # An explicit identity field is rejected even without a value.
])
def test_rejects_explicit_mrn_labels(checker, text):
    result = checker.check_text(text)
    assert BoundaryCategory.MEDICAL_RECORD_NUMBER in {
        finding.category for finding in result.findings
    }
    with pytest.raises(BoundaryValidationError, match="^text_boundary_rejected$"):
        checker.require_text(text)


@pytest.mark.parametrize("text", [
    "Blood pressure 145/90 mmHg; pulse 72 bpm.",
    "Glucose: 123 mg/dL; temperature: 37.2 C.",
    "Synthetic numeric sequence 00012345.",
    "The MRN field is unavailable.", "Medical record number was not provided.",
    "MRN-like wording; record number: 00012345.",
    "XMRN: 00012345", "MRNs: 00012345",
])
def test_mrn_rule_does_not_guess_from_numbers_or_unlabeled_mentions(checker, text):
    assert not checker.check_text(text).has_violations


def test_mrn_findings_and_errors_do_not_reflect_identifier(checker, capsys, caplog):
    text = "MRN: SYNTHETIC-PRIVATE-0001; Medical Record Number#SYNTHETIC-PRIVATE-0002"
    result = checker.check_text(text)
    assert [finding.category for finding in result.findings] == [BoundaryCategory.MEDICAL_RECORD_NUMBER]
    assert all(finding.path == "text" for finding in result.findings)
    assert "SYNTHETIC-PRIVATE" not in json.dumps(asdict(result))
    with pytest.raises(BoundaryValidationError, match="^text_boundary_rejected$"):
        checker.require_text(text)
    assert capsys.readouterr() == ("", "")
    assert not caplog.records


@pytest.mark.parametrize("text", [
    "I have had a headache for three days.",
    "Blood pressure was 145/90 mmHg.",
    "Temperature: 37.2 C; pulse: 72 bpm.",
    "Hemoglobin 13.2 g/dL; weight 65 kg.",
    "LOINC: 789-8 and synthetic code 12345-6.",
    "Recorded at 2026-01-01T12:30:00+00:00.",
    "Recorded at 2026-01-01T12:30:00-05:00.",
    "Synthetic clinical sequence +1 20 30 mg.",
    "Synthetic clinical sequence +1 202 555 0198 milligrams.",
    "Synthetic clinical sequence +1 202 555 0198 units.",
    "Dose 202-555-0198 mg.",
    "Date 2026-01-01; short sequence +1 20 30.",
    "Symptom name: headache; filename: synthetic.txt; namespace: intake.",
])
def test_does_not_misclassify_clinical_text(checker, text):
    assert not checker.check_text(text).has_violations
    assert checker.require_text(text) is None


def test_does_not_apply_unagreed_quasi_identifier_heuristics(checker):
    text = "ZIP 24060; city: Exampletown; gender: female; IP 192.0.2.1."
    assert not checker.check_text(text).has_violations


def test_bare_personal_names_are_a_documented_detection_limit(checker):
    # No fixed glossary and no claim to recognize every name in prose.
    assert not checker.check_text("Mara Quill reports a headache.").has_violations


def test_invalid_email_pipe_is_not_treated_as_a_letter(checker):
    assert not checker.check_text("synthetic@example.c|m").has_violations


def test_results_are_deterministic_and_deduplicate_categories(checker):
    text = (
        "My name is Mara Quill. Contact synthetic@example.com twice: synthetic@example.com. "
        "SSN 000-12-3456; CPF 000.123.456-00. Phone 202-555-0198. MRN: SYNTHETIC-A12."
    )
    first = checker.check_text(text)
    assert first == checker.check_text(text)
    assert [finding.category for finding in first.findings] == [
        BoundaryCategory.EMAIL, BoundaryCategory.GOVERNMENT_ID,
        BoundaryCategory.PHONE, BoundaryCategory.PATIENT_NAME,
        BoundaryCategory.MEDICAL_RECORD_NUMBER,
    ]


def test_results_and_exceptions_never_reflect_submitted_values(checker, capsys, caplog):
    text = "My name is Mara Quill. Contact synthetic.private@example.com."
    result = checker.check_text(text)
    serialized = json.dumps(asdict(result))
    for value in (text, "Mara Quill", "synthetic.private@example.com"):
        assert value not in repr(result)
        assert value not in serialized
    with pytest.raises(BoundaryValidationError) as caught:
        checker.require_text(text)
    assert str(caught.value) == "text_boundary_rejected"
    assert capsys.readouterr() == ("", "")
    assert not caplog.records


@pytest.mark.parametrize("text", [None, b"synthetic report", 1, {}, "", " \n\t", "\ud800"])
def test_invalid_input_is_rejected_instead_of_treated_as_clean(checker, text):
    result = checker.check_text(text)
    assert result.has_violations
    assert result.findings[0].category is BoundaryCategory.INVALID_INPUT
    with pytest.raises(BoundaryValidationError, match="^text_boundary_rejected$"):
        checker.require_text(text)


def test_configured_byte_limit_includes_multibyte_text():
    checker = PIIBoundaryChecker(max_text_bytes=4)
    assert not checker.check_text("abcd").has_violations
    assert not checker.check_text("éé").has_violations
    for text in ("abcde", "ééa"):
        result = checker.check_text(text)
        assert result.findings[0].category is BoundaryCategory.INPUT_TOO_LARGE


def test_default_size_limit_rejects_large_input_before_scanning(checker):
    text = "a" * 16_385
    assert checker.check_text(text).findings[0].category is BoundaryCategory.INPUT_TOO_LARGE


@pytest.mark.parametrize("limit", [0, -1, True, "100", 1.5, None])
def test_size_limit_configuration_must_be_positive_integer(limit):
    with pytest.raises(ValueError, match="^max_text_bytes must be a positive integer$"):
        PIIBoundaryChecker(max_text_bytes=limit)


@pytest.mark.parametrize("text,category", [
    ("synthetic@exam\u200bple.com", BoundaryCategory.EMAIL),
    ("synthetic\uff20example\uff0ecom", BoundaryCategory.EMAIL),
    ("202-555-01\u200b98", BoundaryCategory.PHONE),
    ("\uff12\uff10\uff12-\uff15\uff15\uff15-\uff10\uff11\uff19\uff18", BoundaryCategory.PHONE),
    ("000-12-34\u200b56", BoundaryCategory.GOVERNMENT_ID),
    ("My na\u200bme is Mara Quill", BoundaryCategory.PATIENT_NAME),
    ("synthetic@\u0435x\u0430mpl\u0435.com", BoundaryCategory.EMAIL),
    ("synthetic@\u041a\u041e.example", BoundaryCategory.EMAIL),
    ("My n\u0430m\u0435 is Mara Quill", BoundaryCategory.PATIENT_NAME),
])
def test_normalization_reveals_disguised_identifiers(checker, text, category):
    assert category in {finding.category for finding in checker.check_text(text).findings}
    with pytest.raises(BoundaryValidationError, match="^text_boundary_rejected$"):
        checker.require_text(text)


def test_normalization_cannot_shrink_oversized_input_past_the_limit():
    checker = PIIBoundaryChecker(max_text_bytes=4)
    assert checker.check_text("a\u200b\u200b").findings[0].category is BoundaryCategory.INPUT_TOO_LARGE


@pytest.mark.parametrize("text,limit", [("\ufdfa", 3), ("\u0344", 2)])
def test_normalization_expansion_respects_character_and_byte_limits(text, limit):
    # U+FDFA expands in characters; U+0344 expands from two to four UTF-8 bytes.
    result = PIIBoundaryChecker(max_text_bytes=limit).check_text(text)
    assert result.findings[0].category is BoundaryCategory.INPUT_TOO_LARGE


@pytest.mark.parametrize("char", ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"])
def test_normalized_empty_text_is_invalid(checker, char):
    assert checker.check_text(char).findings[0].category is BoundaryCategory.INVALID_INPUT


@pytest.mark.parametrize("char", ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"])
@pytest.mark.parametrize("template,category", [
    ("synthetic@exam{}ple.com", BoundaryCategory.EMAIL),
    ("My na{}me is Mara Quill", BoundaryCategory.PATIENT_NAME),
])
def test_invisible_format_characters_cannot_hide_identifiers(checker, char, template, category):
    text = template.format(char)
    assert category in {finding.category for finding in checker.check_text(text).findings}
    with pytest.raises(BoundaryValidationError, match="^text_boundary_rejected$"):
        checker.require_text(text)


def test_runtime_normalization_uses_configured_limit_instead_of_tools_default(checker):
    assert not checker.check_text("a" * 10_001).has_violations
