from __future__ import annotations

from typing import Optional

from pydantic import Field

from .location import Resource, TaskType
from .scenario import ShuntingUnit
from .utilities import RailModel, SchemaVersioned


class Action(RailModel):
    """A single action in a shunting plan.

    For Move actions, location is the destination TrackPart ID and resources
    contains the path. For other actions, location is where the action occurs.

    The units an action involves are the ShuntingUnit's members, all of them.
    There was a trainUnitIds field for naming a subset; it was never written by
    the solver, never read by the evaluator on the HIP path, and null in all 606
    actions of every fixture, so it was removed rather than carried further. Note
    for anyone reintroducing per-action subsets: the evaluator reads this format
    through protobuf, and protobuf repeated fields have no presence tracking, so
    on that path "absent" and "empty" arrive identically and cannot mean
    different things without a deliberate design for it.

    That constraint is the evaluator's alone, and is worth not overgeneralising —
    it was read as applying to every consumer once, which is wrong in a way that
    matters: the solver moved off protobuf to System.Text.Json and does
    distinguish the two, which is why it can enforce `required` on read (see its
    NoProto/Location.cs). Any "absent vs empty" reasoning has to be settled per
    consumer.

    TODO: ShuntingUnit is currently embedded in full. Consider switching to
    an ID reference once the evaluator has access to a ShuntingUnit registry
    derived from the Scenario input.
    """

    start_time: Optional[int] = Field(None, alias="startTime")
    end_time: Optional[int] = Field(None, alias="endTime")
    task_type: Optional[TaskType] = Field(None, alias="taskType")
    shunting_unit: Optional[ShuntingUnit] = Field(None, alias="shuntingUnit")
    location: Optional[int] = None
    resources: list[Resource] = Field(default_factory=list)


class Plan(SchemaVersioned):
    """The output of a shunting algorithm: an ordered list of actions.

    There was a trackParts field here, carrying a copy of the Location's track
    graph because the evaluator supposedly could not reach the original. That
    condition no longer holds — run_evaluator.py passes --path_location
    alongside --path_plan — and in practice nothing ever wrote or read it.
    """

    # Required: a plan is its actions. It carried a default until 2026-08-12,
    # which made {} a valid Plan — so a producer that emitted nothing at all
    # passed validation and the emptiness only surfaced downstream, if ever.
    actions: list[Action]
