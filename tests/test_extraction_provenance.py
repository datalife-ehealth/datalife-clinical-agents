"""Extraction adapter identity validation with synthetic metadata only."""

import pytest
from pydantic import ValidationError

from datalife_clinical_agents.schemas import ExtractionProvenance


@pytest.fixture
def provenance_data():
    return {"adapter_name": "synthetic_fixture", "adapter_version": "1"}


def test_valid_provenance_round_trips(provenance_data):
    provenance = ExtractionProvenance.model_validate(provenance_data)
    assert provenance.model_dump() == provenance_data
    assert ExtractionProvenance.model_validate_json(provenance.model_dump_json()) == provenance


@pytest.mark.parametrize("field", ["adapter_name", "adapter_version"])
def test_requires_both_fields(provenance_data, field):
    del provenance_data[field]
    with pytest.raises(ValidationError) as caught:
        ExtractionProvenance.model_validate(provenance_data)
    assert caught.value.errors()[0]["loc"] == (field,)
    assert caught.value.errors()[0]["type"] == "missing"


@pytest.mark.parametrize("field", ["adapter_name", "adapter_version"])
@pytest.mark.parametrize("value", ["", "   ", "\t\n", None, 1, True, b"fixture"])
def test_rejects_blank_or_wrong_type_values(provenance_data, field, value):
    provenance_data[field] = value
    with pytest.raises(ValidationError) as caught:
        ExtractionProvenance.model_validate(provenance_data)
    assert caught.value.errors()[0]["loc"] == (field,)


def test_rejects_unknown_fields(provenance_data):
    provenance_data["approved"] = True
    with pytest.raises(ValidationError) as caught:
        ExtractionProvenance.model_validate(provenance_data)
    assert caught.value.errors()[0]["loc"] == ("approved",)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"
