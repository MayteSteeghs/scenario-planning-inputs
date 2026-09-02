from __future__ import annotations

import logging
from typing import Callable, Optional

from pydantic import Field, NonNegativeInt, model_validator

from .location import TaskType
from .utilities import RailModel, SchemaVersioned, TimeInterval


class TrainUnitType(RailModel):
    """A type of train unit, e.g. SLT or SGM.

    Identity is (type_prefix, carriages): two TrainUnitType instances with
    the same type prefix and carriage count are considered the same type.

    Note: type_prefix is the type family name only ("SLT", "SGM", "VIRM")
    and does NOT encode carriage count. The old convention of "SLT4" / "SLT6"
    is replaced by type_prefix="SLT" + carriages=4. type_display_name is a
    derived value (type_prefix + "-" + carriages) for display/logging only;
    it is not part of the wire schema.
    """

    type_prefix: str = Field(alias="typePrefix")
    carriages: int

    # Optional: all consumers may omit these if not relevant.
    length: Optional[float] = None
    combine_duration: Optional[int] = Field(None, alias="combineDuration")
    split_duration: Optional[int] = Field(None, alias="splitDuration")
    back_norm_time: Optional[int] = Field(None, alias="backNormTime")
    back_addition_time: Optional[int] = Field(None, alias="backAdditionTime")

    # Optional: generator/evaluator only.
    travel_speed: Optional[int] = Field(None, alias="travelSpeed")
    start_up_time: Optional[int] = Field(None, alias="startUpTime")
    needs_loco: bool = Field(False, alias="needsLoco")
    is_loco: bool = Field(False, alias="isLoco")
    needs_electricity: bool = Field(False, alias="needsElectricity")
    id_prefix: Optional[int] = Field(None, alias="idPrefix")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TrainUnitType):
            return NotImplemented
        return self.type_prefix == other.type_prefix and self.carriages == other.carriages

    def __hash__(self) -> int:
        return hash((self.type_prefix, self.carriages))

    @property
    def type_display_name(self) -> str:
        return f"{self.type_prefix}-{self.carriages}"


class TaskSpec(RailModel):
    """A task to be performed on a train unit.

    Note: priority has been dropped from the unified schema and replaced by
    optional. TORS used priority only as a binary 0/non-zero flag; HIP had
    it marked deprecated and unread.
    """

    type: Optional[TaskType] = None
    duration: Optional[int] = None
    # Optional: evaluator/generator only. Empty list means no personnel required.
    required_skills: list[str] = Field(default_factory=list, alias="requiredSkills")
    # False: task must be completed before the train may exit the yard.
    optional: bool = False


class TrainUnit(RailModel):
    """A combination of carriages that can move independently.

    (type_prefix, carriages) is the lookup key into an entry in
    Scenario.train_unit_types. Embedding the full TrainUnitType is
    intentionally avoided to prevent redundancy and inconsistency.
    """

    type_prefix: str = Field(alias="typePrefix")
    carriages: int
    id: Optional[int] = None
    tasks: Optional[list[TaskSpec]] = None

    @property
    def type_display_name(self) -> str:
        return f"{self.type_prefix}-{self.carriages}"


class IncomingTrainUnit(TrainUnit):
    """A TrainUnit as part of an incoming train, with an id and associated tasks."""

    @classmethod
    def from_train_unit(cls, other: TrainUnit) -> IncomingTrainUnit:
        # noinspection PyArgumentList
        return cls(type_prefix=other.type_prefix, carriages=other.carriages, id=other.id, tasks=other.tasks or [])

    id: int
    tasks: list[TaskSpec] = Field(default_factory=list)


class IncomingTrain(RailModel):
    """A train arriving at or already present in the shunting yard.

    Used for both in (arriving) and inStanding (already present) trains.
    """

    entry_track_part: int = Field(alias="entryTrackPart")
    first_parking_track_part: int = Field(alias="firstParkingTrackPart")
    # None for standing trains (already present at scenario start).
    arrival: Optional[int] = None
    departure: Optional[int] = None
    id: Optional[int] = None
    members: list[IncomingTrainUnit] = Field(default_factory=list)
    # Required and mutually distinct within inStanding groups sharing a
    # track (a given fact about the initial state); see the "Standing order"
    # decision in unified-schema-design.md. Enforced by Scenario's
    # cross-record validator, not by this field's own type.
    standing_index: Optional[NonNegativeInt] = Field(None, alias="standingIndex")


class TrainRequest(RailModel):
    """A request for a train to depart from or remain in the shunting yard.

    Used for both out (departing) and outStanding (remaining) trains.
    """

    leave_track_part: int = Field(alias="leaveTrackPart")
    last_parking_track_part: int = Field(alias="lastParkingTrackPart")
    # None for standing trains (remaining at scenario end).
    arrival: Optional[int] = None
    departure: Optional[int] = None
    # Formerly "displayName", which is what the generator called it while
    # assigning it the departing train's id and every consumer treated it as
    # one: the evaluator derives both the Outgoing's and its ShuntingUnit's
    # identity from it, and the solver's only read prints it as "train (id)".
    # The type information the old name implied is carried per unit in
    # train_units, as (type_prefix, carriages).
    id: Optional[int] = None
    # If a TrainUnit's id is None, any unit of the matching type is acceptable.
    train_units: list[TrainUnit] = Field(default_factory=list, alias="trainUnits")
    # Optional within outStanding: null means no preference. See the
    # "Standing order" decision in unified-schema-design.md.
    standing_index: Optional[NonNegativeInt] = Field(None, alias="standingIndex")


class ShuntingUnit(RailModel):
    """A combination of TrainUnits that moves as a single unit at some point
    in time.

    memberIDs is a list of TrainUnit IDs, not embedded objects; consumers that
    need the full TrainUnit look it up via the scenario. Every array of IDs in
    this schema carries the "IDs" suffix, so that a field holding references is
    distinguishable by name from one holding objects — IncomingTrain.members
    genuinely embeds its units.

    Note: standingType has been dropped from the unified schema. StandIn and
    StandOut task types in Plan actions carry this information explicitly.
    """

    id: Optional[int] = None
    member_ids: list[int] = Field(default_factory=list, alias="memberIDs")
    parent_ids: list[int] = Field(default_factory=list, alias="parentIDs")
    child_ids: list[int] = Field(default_factory=list, alias="childIDs")


class NonServiceTraffic(RailModel):
    """Non-service traffic that reserves part of the infrastructure."""

    member_ids: list[int] = Field(default_factory=list, alias="memberIDs")
    arrival: Optional[int] = None
    departure: Optional[int] = None
    id: Optional[int] = None


class DisabledTrackPart(RailModel):
    """A track part that is unavailable during a time window."""

    track_part: Optional[int] = Field(None, alias="trackPart")
    arrival: Optional[int] = None
    departure: Optional[int] = None


class MemberOfStaff(RailModel):
    """A human able to perform tasks at the facility.

    Optional at the Scenario level; omitted for consumers (e.g. the solver)
    that do not model staff.
    """

    id: Optional[int] = None
    type: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    shifts: list[TimeInterval] = Field(default_factory=list)
    break_windows: list[TimeInterval] = Field(default_factory=list, alias="breakWindows")
    break_duration: Optional[float] = Field(None, alias="breakDuration")
    start_location_id: Optional[int] = Field(None, alias="startLocationId")
    end_location_id: Optional[int] = Field(None, alias="endLocationId")
    break_location_id: Optional[int] = Field(None, alias="breakLocationId")
    can_move_trains: Optional[bool] = Field(None, alias="canMoveTrains")
    name: Optional[str] = None


def _validate_standing_group(
    entries: list,
    track_of: Callable[[object], int],
    list_name: str,
    required: bool,
) -> None:
    """Check standingIndex consistency within one Scenario standing list.

    Groups entries by the track they stand on. A track with a single
    standing unit has nothing to be ordered against, so any standingIndex
    set there is decorative (warning only).

    For a track with two or more standing units:
    - required=True (inStanding): standing order is a given fact, so every
      unit must have a standingIndex, and they must be mutually distinct.
    - required=False (outStanding): standing order is an optional terminal
      requirement. All unset means "no preference" and is fine. A *mix* of
      set and unset is still ambiguous (error), as are duplicate values
      among the ones that are set.

    Either way, distinct values that don't form a contiguous 0..N-1
    sequence are allowed (order is still unambiguous) but flagged as a
    warning, since it's a likely sign of a typo or a leftover index from
    elsewhere.
    """
    groups: dict[int, list] = {}
    for entry in entries:
        groups.setdefault(track_of(entry), []).append(entry)

    unordered_tracks = 0

    for track, group in groups.items():
        indices = [entry.standing_index for entry in group]

        if len(group) == 1:
            if indices[0] is not None:
                logging.warning(
                    f"{list_name}: standingIndex is set on track {track}, but it "
                    "is the only standing unit there; the value is unused."
                )
            continue

        set_values = [i for i in indices if i is not None]

        if required:
            if len(set_values) != len(indices):
                raise ValueError(
                    f"{list_name}: track {track} has {len(indices)} standing "
                    "units sharing it, but not all have standingIndex set. "
                    "Standing order is a given fact and must be fully "
                    "specified whenever more than one unit shares a track."
                )
        else:
            if 0 < len(set_values) < len(indices):
                raise ValueError(
                    f"{list_name}: track {track} has a mix of standingIndex "
                    "set and unset among its standing units — either set it "
                    "for all of them (a specific order) or none (no "
                    "preference)."
                )
            if not set_values:
                # No preference among these units — a legitimate, complete
                # specification, not worth a per-track warning. Counted
                # below for a single summary instead.
                unordered_tracks += 1
                continue

        if len(set(set_values)) != len(set_values):
            raise ValueError(
                f"{list_name}: track {track} has two or more standing units "
                "with the same standingIndex; order must be unambiguous."
            )

        if sorted(set_values) != list(range(len(set_values))):
            logging.warning(
                f"{list_name}: track {track}'s standingIndex values "
                f"{sorted(set_values)} are not a contiguous sequence "
                f"starting at 0 ({list(range(len(set_values)))} expected)."
            )

    if unordered_tracks == 1:
        logging.info(f"{list_name}: 1 track has multiple standing trains with no order specified.")
    elif unordered_tracks > 1:
        logging.info(
            f"{list_name}: {unordered_tracks} tracks each have multiple standing trains with no order specified."
        )


class Scenario(SchemaVersioned):
    """The daily-varying part of the problem specification: which trains
    arrive, depart, or remain in the shunting yard.

    TODO: decide whether train_unit_types belongs here (normalized, referenced
    by name from TrainUnit) or embedded in each TrainUnit. Current decision:
    here.
    """

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, exclude_unset=False)

    def to_json(self, **kwargs) -> str:
        return self.model_dump_json(by_alias=True, exclude_unset=False, **kwargs)

    # Required: every TrainUnit references a type by (typePrefix, carriages),
    # so a scenario without this table cannot be resolved. Note that this is the
    # one promotion with a cost — ScenarioGenerator builds a Scenario empty and
    # populates it field by field, so it must now pass train_unit_types=[]
    # explicitly. Requiredness on the wire and construct-then-populate pull in
    # opposite directions; worth remembering before promoting more fields here.
    train_unit_types: list[TrainUnitType] = Field(alias="trainUnitTypes")

    # Trains arriving at and departing from the shunting yard.
    # The HIP-shape split (IncomingTrain / TrainRequest) is used rather than
    # the flat non-HIP Train, which conflated arrival/departure semantics.
    in_: list[IncomingTrain] = Field(default_factory=list, alias="in")
    in_standing: list[IncomingTrain] = Field(default_factory=list, alias="inStanding")
    out: list[TrainRequest] = Field(default_factory=list)
    out_standing: list[TrainRequest] = Field(default_factory=list, alias="outStanding")

    start_time: int = Field(alias="startTime")
    end_time: int = Field(alias="endTime")

    # Optional: generator/evaluator only.
    non_service_traffic: list[NonServiceTraffic] = Field(default_factory=list, alias="nonServiceTraffic")
    disabled_track_parts: list[DisabledTrackPart] = Field(default_factory=list, alias="disabledTrackPart")
    workers: list[MemberOfStaff] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_standing_order(self) -> "Scenario":
        _validate_standing_group(
            self.in_standing,
            lambda t: t.first_parking_track_part,
            "inStanding",
            required=True,
        )
        _validate_standing_group(
            self.out_standing,
            lambda t: t.last_parking_track_part,
            "outStanding",
            required=False,
        )
        return self
