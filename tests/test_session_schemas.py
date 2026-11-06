"""Session contract tests using invented reports and identifiers only."""

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from datalife_clinical_agents.schemas import (
    IntakeInput,
    Modality,
    SessionInputV1,
)


@pytest.fixture
def session_data():
    return {
        "subject_key": "synthetic-subject-001",
        "intake_input": {"raw_text": "I have had a headache for three days."},
        "session_metadata": {
            "session_id": UUID("00000000-0000-4000-8000-000000000001"),
            "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
        },
    }


def test_submitted_session_preserves_values_and_serializes_version(session_data):
    session = SessionInputV1.model_validate(session_data)

    assert session.subject_key == session_data["subject_key"]
    assert session.intake_input.raw_text == session_data["intake_input"]["raw_text"]
    assert session.intake_input.modality is Modality.TEXT
    assert session.session_metadata.session_id == session_data["session_metadata"]["session_id"]
    assert json.loads(session.model_dump_json())["schema_version"] == "1"


@pytest.mark.parametrize("field", ["subject_key", "intake_input", "session_metadata"])
def test_submitted_session_requires_explicit_fields(session_data, field):
    del session_data[field]
    with pytest.raises(ValidationError) as caught:
        SessionInputV1.model_validate(session_data)
    assert caught.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize("field", ["session_id", "timestamp"])
def test_metadata_requires_stable_values(session_data, field):
    del session_data["session_metadata"][field]
    with pytest.raises(ValidationError) as caught:
        SessionInputV1.model_validate(session_data)
    assert caught.value.errors()[0]["loc"] == ("session_metadata", field)


@pytest.mark.parametrize("text", [None, "", "   ", "\t\n", b"Synthetic report", 123])
def test_rejects_missing_blank_or_wrong_type_text(text):
    with pytest.raises(ValidationError):
        IntakeInput(raw_text=text)


def test_text_is_required():
    with pytest.raises(ValidationError):
        IntakeInput()


def test_preserves_original_whitespace():
    report = "  Synthetic headache report.\n"
    assert IntakeInput(raw_text=report).raw_text == report


@pytest.mark.parametrize("key", ["", "abc", "    ", "x" * 65, 123, b"subj-001"])
def test_rejects_invalid_subject_keys(session_data, key):
    session_data["subject_key"] = key
    with pytest.raises(ValidationError):
        SessionInputV1.model_validate(session_data)


@pytest.mark.parametrize("key", ["s" * 4, "s" * 64])
def test_accepts_core_subject_key_length_boundaries(session_data, key):
    session_data["subject_key"] = key
    assert SessionInputV1.model_validate(session_data).subject_key == key


@pytest.mark.parametrize("path", [(), ("intake_input",), ("session_metadata",)])
def test_rejects_unknown_privileged_fields_at_every_level(session_data, path):
    target = session_data
    for part in path:
        target = target[part]
    target["approved"] = True
    with pytest.raises(ValidationError) as caught:
        SessionInputV1.model_validate(session_data)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"
    assert caught.value.errors()[0]["loc"] == (*path, "approved")


@pytest.mark.parametrize("version", ["2", "", 1, None])
def test_rejects_unsupported_versions(session_data, version):
    session_data["schema_version"] = version
    with pytest.raises(ValidationError) as caught:
        SessionInputV1.model_validate(session_data)
    assert caught.value.errors()[0]["type"] == "literal_error"


def test_rejects_naive_timestamp(session_data):
    session_data["session_metadata"]["timestamp"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError) as caught:
        SessionInputV1.model_validate(session_data)
    assert caught.value.errors()[0]["type"] == "timezone_aware"


def test_python_metadata_requires_typed_objects(session_data):
    session_data["session_metadata"]["session_id"] = "00000000-0000-4000-8000-000000000001"
    with pytest.raises(ValidationError):
        SessionInputV1.model_validate(session_data)


def test_json_round_trip_accepts_uuid_datetime_and_modality_strings(session_data):
    session_data["intake_input"]["modality"] = Modality.AUDIO
    original = SessionInputV1.model_validate(session_data)

    # JSON has no UUID, datetime, or enum types, so their string forms are valid.
    restored = SessionInputV1.model_validate_json(original.model_dump_json())

    assert restored == original
    assert restored.intake_input.modality is Modality.AUDIO


def test_rejects_unsupported_json_modality(session_data):
    payload = SessionInputV1.model_validate(session_data).model_dump(mode="json")
    payload["intake_input"]["modality"] = "audio_file"
    with pytest.raises(ValidationError):
        SessionInputV1.model_validate_json(json.dumps(payload))


def test_identical_input_keeps_identical_session_identity(session_data):
    first = SessionInputV1.model_validate(session_data)
    retry = SessionInputV1.model_validate(session_data)
    assert first.model_dump_json() == retry.model_dump_json()


def test_normal_representation_omits_sensitive_content(session_data):
    session = SessionInputV1.model_validate(session_data)
    assert session.intake_input.raw_text not in repr(session)
    assert session.subject_key not in repr(session)


def test_validation_error_string_omits_rejected_value(session_data):
    rejected_value = "synthetic-secret-" + "x" * 65
    session_data["subject_key"] = rejected_value
    with pytest.raises(ValidationError) as caught:
        SessionInputV1.model_validate(session_data)
    assert rejected_value not in str(caught.value)
