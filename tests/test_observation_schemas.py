"""Synthetic examples of typed observations, uncertainty, and abstention."""

import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from datalife_clinical_agents.schemas import (
    BloodPressureValue,
    ObservationV1,
    SymptomValue,
)


@pytest.fixture
def observation_data():
    return {
        "provenance": {
            "session_id": UUID("00000000-0000-4000-8000-000000000001"),
        },
        "value_unit": {
            "observation_type": "symptom",
            "symptom": "headache",
            "duration_days": 3.0,
        },
        "uncertainty": {"is_uncertain": False, "abstained": False},
    }


def test_symptom_keeps_reported_details_and_unknown_confidence(observation_data):
    observation = ObservationV1.model_validate(observation_data)
    assert isinstance(observation.value_unit, SymptomValue)
    assert observation.value_unit.symptom == "headache"
    assert observation.value_unit.duration_days == 3.0
    assert observation.uncertainty.confidence_score is None
    assert observation.provenance.source == "self_reported"
    assert observation.provenance.session_id == observation_data["provenance"]["session_id"]
    assert observation.model_dump(mode="json")["schema_version"] == "1"


def test_blood_pressure_uses_separate_typed_measurements(observation_data):
    observation_data["value_unit"] = {
        "observation_type": "blood_pressure", "systolic": 145, "diastolic": 90,
    }
    observation = ObservationV1.model_validate(observation_data)
    assert isinstance(observation.value_unit, BloodPressureValue)
    assert observation.value_unit.systolic == 145
    assert observation.value_unit.diastolic == 90
    assert observation.value_unit.unit == "mmHg"


def test_json_round_trip_preserves_uncertainty(observation_data):
    observation_data["uncertainty"].update(is_uncertain=True, confidence_score=1.0)
    observation = ObservationV1.model_validate(observation_data)
    restored = ObservationV1.model_validate_json(observation.model_dump_json())
    assert restored == observation
    assert restored.uncertainty.is_uncertain is True


def test_missing_duration_remains_unknown(observation_data):
    del observation_data["value_unit"]["duration_days"]
    observation = ObservationV1.model_validate(observation_data)
    assert observation.value_unit.duration_days is None


@pytest.mark.parametrize("value", ["", " \t", 1, True, b"headache"])
def test_rejects_invalid_symptom_text(observation_data, value):
    observation_data["value_unit"]["symptom"] = value
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan"), "3", True])
def test_rejects_invalid_duration(observation_data, value):
    observation_data["value_unit"]["duration_days"] = value
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("field", ["systolic", "diastolic"])
@pytest.mark.parametrize("value", [0, -1, True, "145", 145.5])
def test_rejects_wrong_measurement_types_and_nonpositive_values(observation_data, field, value):
    observation_data["value_unit"] = {
        "observation_type": "blood_pressure", "systolic": 145, "diastolic": 90,
    }
    observation_data["value_unit"][field] = value
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


def test_rejects_incompatible_blood_pressure_unit(observation_data):
    observation_data["value_unit"] = {
        "observation_type": "blood_pressure", "systolic": 145, "diastolic": 90,
        "unit": "mg/dL",
    }
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf"), float("nan"), "0.5", True])
def test_rejects_invalid_confidence(observation_data, value):
    observation_data["uncertainty"]["confidence_score"] = value
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("value", [None, 0.0, 0.5, 1.0])
def test_accepts_unknown_or_bounded_confidence(observation_data, value):
    observation_data["uncertainty"]["confidence_score"] = value
    assert ObservationV1.model_validate(observation_data).uncertainty.confidence_score == value


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_abstention_requires_meaningful_reason(observation_data, reason):
    observation_data["uncertainty"].update(abstained=True, abstained_reason=reason)
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


def test_reason_cannot_contradict_abstention_flag(observation_data):
    observation_data["uncertainty"]["abstained_reason"] = "Synthetic missing detail"
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("payload", [
    {"observation_type": "symptom"},
    {"observation_type": "blood_pressure", "systolic": 145},
    {"observation_type": "blood_pressure", "diastolic": 90},
])
def test_incomplete_observations_require_abstention(observation_data, payload):
    observation_data["value_unit"] = payload
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


def test_abstention_preserves_partial_measurement(observation_data):
    observation_data["value_unit"] = {
        "observation_type": "blood_pressure", "systolic": 145,
    }
    observation_data["uncertainty"].update(
        abstained=True, abstained_reason="Diastolic value was not reported.",
    )
    observation = ObservationV1.model_validate(observation_data)
    assert observation.value_unit.systolic == 145
    assert observation.value_unit.diastolic is None
    assert observation.uncertainty.abstained is True


def test_abstention_does_not_skip_type_validation(observation_data):
    observation_data["value_unit"] = {
        "observation_type": "blood_pressure", "systolic": "unknown",
    }
    observation_data["uncertainty"].update(
        abstained=True, abstained_reason="Synthetic ambiguous measurement.",
    )
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("section", [None, "provenance", "value_unit", "uncertainty"])
def test_rejects_privileged_fields_at_every_level(observation_data, section):
    target = observation_data if section is None else observation_data[section]
    target["approved"] = True
    with pytest.raises(ValidationError) as caught:
        ObservationV1.model_validate(observation_data)
    assert any(error["type"] == "extra_forbidden" for error in caught.value.errors())


@pytest.mark.parametrize("field", ["provenance", "value_unit", "uncertainty"])
def test_requires_observation_sections(observation_data, field):
    del observation_data[field]
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


def test_requires_provenance_session_id(observation_data):
    observation_data["provenance"] = {}
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


def test_rejects_claim_of_verified_provenance(observation_data):
    observation_data["provenance"]["source"] = "clinician_verified"
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("field", ["is_uncertain", "abstained"])
def test_requires_explicit_uncertainty_flags(observation_data, field):
    del observation_data["uncertainty"][field]
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


@pytest.mark.parametrize("version", ["2", 1, None])
def test_rejects_unsupported_version(observation_data, version):
    observation_data["schema_version"] = version
    with pytest.raises(ValidationError):
        ObservationV1.model_validate(observation_data)


def test_unknown_observation_type_fails_closed_in_json(observation_data):
    observation = ObservationV1.model_validate(observation_data)
    payload = observation.model_dump(mode="json")
    payload["value_unit"] = {"observation_type": "diagnosis", "value": "invented"}
    with pytest.raises(ValidationError) as caught:
        ObservationV1.model_validate_json(json.dumps(payload))
    assert caught.value.errors()[0]["type"] == "union_tag_invalid"


def test_representation_omits_free_text(observation_data):
    observation_data["uncertainty"].update(
        abstained=True, abstained_reason="Synthetic ambiguous symptom report.",
    )
    observation = ObservationV1.model_validate(observation_data)
    assert observation.value_unit.symptom not in repr(observation)
    assert observation.uncertainty.abstained_reason not in repr(observation)
