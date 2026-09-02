from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field, model_validator

from .utilities import RailModel, SchemaVersioned, TimeInterval


class TrackPartType(str, Enum):
    RAILROAD = "RailRoad"
    SWITCH = "Switch"
    ENGLISH_SWITCH = "EnglishSwitch"
    # Deprecated: present in both proto models, keep for backwards compatibility.
    HALF_ENGLISH_SWITCH = "HalfEnglishSwitch"
    INTERSECTION = "Intersection"
    BUMPER = "Bumper"
    # Only meaningful to the generator and evaluator; the solver will not
    # encounter this value but should tolerate it.
    BUILDING = "Building"


class PredefinedTaskType(str, Enum):
    # Movement
    MOVE = "Move"
    SPLIT = "Split"
    COMBINE = "Combine"
    # Waiting / lifecycle
    WAIT = "Wait"
    ARRIVE = "Arrive"
    EXIT = "Exit"
    # Standing-train equivalents of Arrive/Exit, used in Plan actions.
    STAND_IN = "StandIn"
    STAND_OUT = "StandOut"
    # Staff / facility
    WALKING = "Walking"
    BREAK = "Break"
    # Infrastructure
    NON_SERVICE = "NonService"
    # NOTE: BeginMove and EndMove are evaluator-internal concepts and are
    # intentionally absent from the interchange schema.


class TaskType(RailModel):
    """A task type, either one of the well-known predefined values or a
    custom string for facility-specific tasks."""

    predefined: Optional[PredefinedTaskType] = None
    other: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_set(self) -> TaskType:
        set_fields = sum([self.predefined is not None, self.other is not None])
        if set_fields != 1:
            raise ValueError("Exactly one of 'predefined' or 'other' must be set.")
        return self


class TrackPart(RailModel):
    """A single node in the rail graph."""

    id: int
    type: Optional[TrackPartType] = None
    a_side: list[int] = Field(default_factory=list, alias="aSide")
    b_side: list[int] = Field(default_factory=list, alias="bSide")
    length: Optional[float] = None
    name: Optional[str] = None
    saw_movement_allowed: bool = Field(False, alias="sawMovementAllowed")
    parking_allowed: bool = Field(False, alias="parkingAllowed")
    # Optional: evaluator/generator only.
    is_electrified: Optional[bool] = Field(None, alias="isElectrified")
    station_platform: Optional[bool] = Field(None, alias="stationPlatform")


class Facility(RailModel):
    """An object at the location that is not part of the rails (e.g. a
    cleaning platform or a washing installation)."""

    id: Optional[int] = None
    type: Optional[str] = None
    related_track_part_ids: list[int] = Field(default_factory=list, alias="relatedTrackPartIDs")
    task_types: list[TaskType] = Field(default_factory=list, alias="taskTypes")
    simultaneous_usage_count: Optional[int] = Field(None, alias="simultaneousUsageCount")
    # Optional: evaluator/generator only.
    time_window: Optional[TimeInterval] = Field(None, alias="timeWindow")


class ResourceKind(str, Enum):
    TRACK_PART = "trackPart"
    FACILITY = "facility"
    # staff resources are only present in generator/evaluator output; the
    # solver will not produce this kind but the unified schema includes it.
    STAFF = "staff"


class Resource(RailModel):
    """A resource involved in an action: either a TrackPart, a Facility,
    or a member of staff, identified by an explicit kind discriminator."""

    kind: ResourceKind
    id: int


class WalkingDistanceEntry(RailModel):
    """An entry in the walking distance matrix between track parts."""

    from_track_part_id: int = Field(alias="fromTrackPartId")
    to_track_part_id: int = Field(alias="toTrackPartId")
    distance_in_seconds: float = Field(alias="distanceInSeconds")


class Location(SchemaVersioned):
    """The fixed part of the problem specification: track layout and
    facilities. Does not change on a daily basis."""

    # Required, unlike the two below: a Location without trackParts is not a
    # partially-specified location, it is not a location. With a default it
    # validated, so {} was a valid Location and a fixture sweep reporting
    # "N/N valid" said less than it appeared to. An empty list still validates
    # — `required` is key presence only — but the corpus has no such file, and
    # minItems was left off deliberately (see SCHEMA_CHANGELOG.md).
    track_parts: list[TrackPart] = Field(alias="trackParts")
    # Optional: a location may genuinely have no facilities and no task types.
    facilities: list[Facility] = Field(default_factory=list, alias="facilities")
    task_types: list[TaskType] = Field(default_factory=list, alias="taskTypes")

    # Optional: evaluator/generator only. Used for shunting time calculations.
    # These constants/coefficients are nominally global, but individual
    # locations might differ.
    movement_constant: Optional[int] = Field(None, alias="movementConstant")
    movement_track_coefficient: Optional[int] = Field(None, alias="movementTrackCoefficient")
    movement_switch_coefficient: Optional[int] = Field(None, alias="movementSwitchCoefficient")
    # Optional: evaluator/generator only. Walking distance matrix.
    distance_entries: list[WalkingDistanceEntry] = Field(default_factory=list, alias="distanceEntries")
