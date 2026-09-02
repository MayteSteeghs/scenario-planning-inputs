"""Model for the generator's input configuration files.

These are the `scenario_config_*.json` files under a location's
`configurations/` directory in scenario-planning-inputs. Unlike Location,
Scenario and Plan, they are not interchange: nothing downstream reads them,
and they are the only inputs in the pipeline written by hand rather than
generated. That is precisely why they are worth a schema — a mistyped optional
key is otherwise accepted in silence and simply does not take effect.

`check_config.py` keeps the work a schema cannot do: checking values against the
location and the material catalogue, and normalising the config in place (it
sets `location_file`, defaults `number_of_trains`, and injects derived
distribution values). This model covers shape only.

Wire names are snake_case here, matching the files, so no aliases are needed —
these configurations are not part of the camelCase interchange format.
"""

from __future__ import annotations

from typing import Optional, Union

from pydantic import Field
from typing_extensions import Annotated, Literal

from .utilities import RailModel


class Intent(RailModel):
    """Why a configuration exists and what it is meant to exercise.

    Free prose, but structured prose: recorded so that a scenario's purpose
    survives the person who wrote it. Carried through to nothing — the
    generator ignores it — which is exactly why it needs to be declared here.
    Left undeclared, it would have to be admitted by permitting unknown keys,
    and that same permission is what lets a typo through unnoticed.
    """

    designed_for: Optional[str] = None
    expectation: Optional[str] = None
    exercises: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class TrainUnitDistribution(RailModel):
    """How randomly generated material is drawn.

    Note the spelling: instanding_ratio and outstanding_ratio, both lowercase.
    scenario_config_test.json carried inStanding_ratio/outStanding_ratio, which
    random_generator.py never reads, so those settings had no effect. They were
    both 0.0 and the no-key fallback is also "none", so nothing observable
    changed — which is how it survived. This model rejects that spelling.

    servicing_ratio and tasks_per_train_unit are optional inputs with defaults
    applied by check_config.py. number_trains_in, number_trains_out and
    average_servicing_time are deliberately absent: they are derived, and
    setting them by hand would be a mistake worth reporting.
    """

    train_unit_types: list[str] = Field(default_factory=list)
    units_per_composition: list[int] = Field(default_factory=list)
    super_type_ratio: Optional[float] = None
    matching_complexity: Optional[float] = None
    instanding_ratio: Optional[float] = None
    outstanding_ratio: Optional[float] = None
    servicing_ratio: Optional[float] = None
    tasks_per_train_unit: Optional[int] = None


class Gateway(RailModel):
    """The track parts trains may arrive over and depart from, by name."""

    arrival: list[str] = Field(default_factory=list)
    departure: list[str] = Field(default_factory=list)


class _ScenarioConfigBase(RailModel):
    """Fields common to both kinds of configuration."""

    location: str
    start_time: int
    end_time: int
    perform_servicing: bool
    intent: Optional[Intent] = None

    # use_default_material=False means the train unit types are generated too,
    # and these two become required — a rule check_config.py enforces, since it
    # cuts across the trains_given split that discriminates the union below.
    use_default_material: bool
    number_of_train_unit_types: Optional[int] = None
    custom_train_unit_types: Optional[list[dict]] = None

    track_ids_used: Optional[bool] = None


class CustomTrainsConfig(_ScenarioConfigBase):
    """trains_given=true: the trains are spelled out rather than drawn.

    The custom_* payloads are typed only as objects for now. The value of this
    schema is at the top level, where the optional knobs live and where a typo
    goes unnoticed; the nested shapes are involved enough to deserve their own
    pass rather than a guess.
    """

    trains_given: Literal[True]
    custom_trains: list[dict] = Field(default_factory=list)
    custom_train_units: list[dict] = Field(default_factory=list)
    custom_servicing_tasks: list[dict] = Field(default_factory=list)
    partial_matching_given: Optional[bool] = None
    partial_plan_given: Optional[bool] = None
    through_traffic_given: Optional[bool] = None


class GeneratedTrainsConfig(_ScenarioConfigBase):
    """trains_given=false: the trains are drawn from a distribution."""

    trains_given: Literal[False]
    number_of_trains: Optional[int] = None
    train_unit_distribution: Optional[TrainUnitDistribution] = None
    gateway: Optional[Gateway] = None
    matching: Optional[int] = None
    min_gap_on_gateway: Optional[int] = None
    min_time_in_yard: Optional[int] = None
    mixed_traffic: Optional[bool] = None
    seed: Optional[int] = None


# trains_given picks the family, and every configuration sets it.
ScenarioConfig = Annotated[
    Union[CustomTrainsConfig, GeneratedTrainsConfig],
    Field(discriminator="trains_given"),
]
