"""Tests for the typePrefix/carriages identity rename and TaskSpec.optional
(Phase 2 of the 2.0.0 roadmap, see unified-schema-design.md)."""

import logging

import pytest
from pydantic import TypeAdapter, ValidationError

from robust_rail_models.scenario import (
    IncomingTrain,
    IncomingTrainUnit,
    Scenario,
    TaskSpec,
    TrainRequest,
    TrainUnit,
    TrainUnitType,
)
from robust_rail_models.scenario_config import (
    CustomTrainsConfig,
    GeneratedTrainsConfig,
    ScenarioConfig,
    TrainUnitDistribution,
)


class TestTrainUnitType:
    def test_identity_is_type_prefix_and_carriages(self):
        a = TrainUnitType(type_prefix="SLT", carriages=4)
        b = TrainUnitType(type_prefix="SLT", carriages=4)
        c = TrainUnitType(type_prefix="SLT", carriages=6)
        assert a == b
        assert hash(a) == hash(b)
        assert a != c

    def test_type_display_name_is_derived_not_a_wire_field(self):
        t = TrainUnitType(type_prefix="SLT", carriages=4)
        assert t.type_display_name == "SLT-4"
        assert "typeDisplayName" not in t.to_dict()

    def test_wire_shape_uses_type_prefix(self):
        t = TrainUnitType.model_validate({"typePrefix": "VIRM", "carriages": 6})
        assert t.type_prefix == "VIRM"
        assert t.to_dict()["typePrefix"] == "VIRM"
        assert "displayName" not in t.to_dict()

    def test_display_name_rejected_as_extra_field(self):
        with pytest.raises(Exception):
            TrainUnitType.model_validate({"displayName": "SLT", "carriages": 4})


class TestTrainUnit:
    def test_type_prefix_and_carriages_are_required(self):
        u = TrainUnit(type_prefix="SLT", carriages=4)
        assert u.type_display_name == "SLT-4"
        assert u.to_dict()["typePrefix"] == "SLT"
        assert u.to_dict()["carriages"] == 4

    def test_incoming_train_unit_from_train_unit_copies_type_fields(self):
        base = TrainUnit(type_prefix="VIRM", carriages=6, id=2401)
        incoming = IncomingTrainUnit.from_train_unit(base)
        assert incoming.type_prefix == "VIRM"
        assert incoming.carriages == 6
        assert incoming.id == 2401


class TestTaskSpec:
    def test_optional_defaults_false(self):
        spec = TaskSpec()
        assert spec.optional is False

    def test_optional_omitted_from_wire_when_unset(self):
        spec = TaskSpec(duration=60)
        assert "optional" not in spec.to_dict()

    def test_optional_present_when_explicitly_set(self):
        spec = TaskSpec(duration=60, optional=True)
        assert spec.to_dict()["optional"] is True


def _scenario(**overrides):
    kwargs = dict(train_unit_types=[], in_=[], out=[], start_time=0, end_time=100)
    kwargs.update(overrides)
    return Scenario(**kwargs)


def _incoming(track, standing_index, id_):
    return IncomingTrain(
        entry_track_part=1,
        first_parking_track_part=track,
        id=id_,
        standing_index=standing_index,
    )


def _request(track, standing_index, id_):
    return TrainRequest(
        leave_track_part=1,
        last_parking_track_part=track,
        id=id_,
        standing_index=standing_index,
    )


class TestStandingOrder:
    """solver#17/#18 and unified-schema-design.md's "Standing order" section:
    inStanding order is a given fact and must be fully, unambiguously
    specified wherever a track has more than one standing unit; outStanding
    order is an optional terminal requirement, where "no preference" (all
    unset) is legitimate but a partial mix of set/unset is still ambiguous.
    """

    def test_instanding_distinct_indices_are_accepted(self):
        _scenario(in_standing=[_incoming(5, 0, 1), _incoming(5, 1, 2)])

    def test_instanding_duplicate_index_is_rejected(self):
        with pytest.raises(ValidationError):
            _scenario(in_standing=[_incoming(5, 0, 1), _incoming(5, 0, 2)])

    def test_instanding_missing_index_is_rejected_when_track_is_shared(self):
        with pytest.raises(ValidationError):
            _scenario(in_standing=[_incoming(5, 0, 1), _incoming(5, None, 2)])

    def test_instanding_index_on_a_singleton_track_is_not_required(self):
        _scenario(in_standing=[_incoming(5, None, 1)])

    def test_instanding_singleton_track_with_index_set_warns(self, caplog):
        with caplog.at_level(logging.WARNING):
            _scenario(in_standing=[_incoming(5, 0, 1)])
        assert "unused" in caplog.text

    def test_instanding_out_of_sequence_indices_warn_but_are_accepted(self, caplog):
        with caplog.at_level(logging.WARNING):
            _scenario(in_standing=[_incoming(5, 0, 1), _incoming(5, 2, 2)])
        assert "not a contiguous sequence" in caplog.text

    def test_outstanding_all_unset_is_accepted_as_no_preference(self):
        _scenario(out_standing=[_request(5, None, 1), _request(5, None, 2)])

    def test_outstanding_all_unset_does_not_warn(self, caplog):
        with caplog.at_level(logging.WARNING):
            _scenario(out_standing=[_request(5, None, 1), _request(5, None, 2)])
        assert "outStanding" not in caplog.text

    def test_outstanding_all_unset_logs_one_info_summary(self, caplog):
        with caplog.at_level(logging.INFO):
            _scenario(out_standing=[_request(5, None, 1), _request(5, None, 2)])
        assert "1 track has multiple standing trains with no order specified" in caplog.text

    def test_outstanding_mixed_set_and_unset_is_rejected(self):
        with pytest.raises(ValidationError):
            _scenario(out_standing=[_request(5, 0, 1), _request(5, None, 2)])

    def test_outstanding_duplicate_index_is_rejected(self):
        with pytest.raises(ValidationError):
            _scenario(out_standing=[_request(5, 0, 1), _request(5, 0, 2)])

    def test_outstanding_distinct_indices_are_accepted(self):
        _scenario(out_standing=[_request(5, 0, 1), _request(5, 1, 2)])


class TestScenarioConfig:
    """The configuration files are the only pipeline input written by hand, and
    check_config.py accepts any key it does not recognise — so a mistyped
    optional key has always been ignored rather than reported. These cover the
    part of that gap the model closes."""

    def test_trains_given_selects_the_custom_form(self):
        config = TypeAdapter(ScenarioConfig).validate_python(
            {
                "location": "loc",
                "start_time": 0,
                "end_time": 3600,
                "use_default_material": True,
                "perform_servicing": False,
                "trains_given": True,
                "custom_trains": [],
                "custom_train_units": [],
            }
        )
        assert isinstance(config, CustomTrainsConfig)

    def test_trains_given_false_selects_the_generated_form(self):
        config = TypeAdapter(ScenarioConfig).validate_python(
            {
                "location": "loc",
                "start_time": 0,
                "end_time": 3600,
                "use_default_material": True,
                "perform_servicing": False,
                "trains_given": False,
                "number_of_trains": 4,
                "seed": 1,
            }
        )
        assert isinstance(config, GeneratedTrainsConfig)

    def test_a_mistyped_optional_key_is_rejected(self):
        with pytest.raises(ValidationError):
            TypeAdapter(ScenarioConfig).validate_python(
                {
                    "location": "loc",
                    "start_time": 0,
                    "end_time": 3600,
                    "use_default_material": True,
                    "perform_servicing": False,
                    "trains_given": False,
                    "min_time_in_yards": 600,
                }
            )

    def test_the_camelcase_standing_ratios_are_rejected(self):
        """scenario_config_test.json carried inStanding_ratio/outStanding_ratio,
        which random_generator.py never reads, so they quietly did nothing."""
        with pytest.raises(ValidationError):
            TrainUnitDistribution(train_unit_types=["VIRM-4"], inStanding_ratio=0.3)

    def test_intent_is_a_declared_field_not_a_tolerated_extra(self):
        config = TypeAdapter(ScenarioConfig).validate_python(
            {
                "location": "loc",
                "start_time": 0,
                "end_time": 3600,
                "use_default_material": True,
                "perform_servicing": False,
                "trains_given": False,
                "intent": {"designed_for": "domain", "notes": ["a", "b"]},
            }
        )
        assert config.intent.designed_for == "domain"
        assert config.intent.notes == ["a", "b"]
