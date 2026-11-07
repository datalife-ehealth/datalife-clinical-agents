"""Synthetic core request shapes; no ingestion API calls."""

import json

import pytest
from pydantic import ValidationError

from datalife_clinical_agents.schemas import IngestionEnvelopeV1


@pytest.fixture
def envelope_data():
    return {
        "subject_key": "b4c3c202-31f4-4f10-8b49-0d067a2fc1e8",
        "body": '{"schema_version":"1","observations":[]}',
    }


def test_envelope_has_exact_core_outer_fields(envelope_data):
    envelope = IngestionEnvelopeV1.model_validate(envelope_data)
    payload = envelope.model_dump()
    assert payload == {
        **envelope_data, "kind": "json", "media_type": "application/json",
    }
    assert isinstance(payload["body"], str)
    assert IngestionEnvelopeV1.model_validate_json(envelope.model_dump_json()) == envelope


@pytest.mark.parametrize("field", ["subject_key", "body"])
def test_envelope_requires_explicit_input(envelope_data, field):
    del envelope_data[field]
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert caught.value.errors()[0]["loc"] == (field,)
    assert caught.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize("subject", [
    "", "abc", "    ", "x" * 65, 1, b"subj-001", None,
    "synthetic@example.com", "202-555-0198", "Mara Quill",
    "b4c3c202-31f4-1f10-8b49-0d067a2fc1e8",
    "b4c3c202-31f4-3f10-8b49-0d067a2fc1e8",
    "b4c3c202-31f4-5f10-8b49-0d067a2fc1e8",
    "00000000-0000-0000-0000-000000000000",
    "B4C3C202-31F4-4F10-8B49-0D067A2FC1E8",
    "b4c3c20231f44f108b490d067a2fc1e8",
    "{b4c3c202-31f4-4f10-8b49-0d067a2fc1e8}",
    "urn:uuid:b4c3c202-31f4-4f10-8b49-0d067a2fc1e8",
])
def test_rejects_invalid_subject_key(envelope_data, subject):
    envelope_data["subject_key"] = subject
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert caught.value.errors()[0]["loc"] == ("subject_key",)


@pytest.mark.parametrize("subject", [
    "b4c3c202-31f4-4f10-8b49-0d067a2fc1e8",
    "a3d78675-4d22-4231-9b86-58c0bd60ab9f",
])
def test_accepts_canonical_uuid4_subject_string(envelope_data, subject):
    envelope_data["subject_key"] = subject
    assert IngestionEnvelopeV1.model_validate(envelope_data).subject_key == subject


@pytest.mark.parametrize("body", [
    "", "   ", "{", '{"value":}', '{"value":1,}', '{} {}',
    "[]", "null", "true", "42", '"a string"',
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e400}', '{"value":-1e400}',
    '{"value":1,"value":2}',
    '{"nested":{"value":1,"value":2}}',
    '{"nested":[{"value":1,"value":2}]}',
    '{"value":1,"\\u0076alue":2}',
    '{"text":"\ud800"}',
])
def test_rejects_invalid_or_unsupported_json_bodies(envelope_data, body):
    envelope_data["body"] = body
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert caught.value.errors()[0]["loc"] == ("body",)


@pytest.mark.parametrize("body", [{"value": 1}, b"{}", 1, None])
def test_body_must_already_be_a_string(envelope_data, body):
    envelope_data["body"] = body
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert caught.value.errors()[0]["type"] == "string_type"


@pytest.mark.parametrize("body", [
    "{}", ' \n { "value" : 1.5 } \t',
    '{"a":{"value":1},"b":{"value":2}}',
    '{"observations":[],"missing":null,"uncertain":true}',
    '{"text":"NaN and Infinity are just words here"}',
    '{"text":"Synthetic café report"}',
])
def test_valid_object_text_is_preserved_exactly(envelope_data, body):
    envelope_data["body"] = body
    envelope = IngestionEnvelopeV1.model_validate(envelope_data)
    assert envelope.body == body
    assert json.loads(envelope.model_dump_json())["body"] == body


@pytest.mark.parametrize("field,value", [
    ("kind", "xml"), ("kind", "dicom"), ("kind", None),
    ("media_type", "application/xml"), ("media_type", "application/octet-stream"),
    ("media_type", None),
])
def test_rejects_unsupported_kind_and_media_type(envelope_data, field, value):
    envelope_data[field] = value
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert caught.value.errors()[0]["loc"] == (field,)


@pytest.mark.parametrize("field", ["approved", "body_dict", "body_serialized", "schema_version"])
def test_rejects_extra_outer_fields(envelope_data, field):
    envelope_data[field] = True
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_normal_representation_omits_subject_and_body(envelope_data):
    envelope = IngestionEnvelopeV1.model_validate(envelope_data)
    assert envelope.subject_key not in repr(envelope)
    assert envelope.body not in repr(envelope)


def test_json_failure_message_does_not_echo_body(envelope_data):
    envelope_data["body"] = '{"synthetic-private-fragment":'
    with pytest.raises(ValidationError) as caught:
        IngestionEnvelopeV1.model_validate(envelope_data)
    assert "synthetic-private-fragment" not in str(caught.value)
