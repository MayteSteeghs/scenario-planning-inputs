# 2.0.0 release — open items

2.0.0 shipped 2026-08-24 (all four PRs sharing the interchange format merged;
see [`roadmap-2.0.0-history.md`](roadmap-2.0.0-history.md) for the full
verification log, resolved decisions, and what was done in each phase). This
file now holds only what's still open — kept short on the assumption most of
it either closes out or goes stale; check the dates before trusting anything
below.

---

## Known issues (open upstream, checked 2026-08-27)

| issue | effect |
|---|---|
| solver#13 | Solver parks on non-parking arrival tracks when it cannot move into the yard immediately. Blocks `6t_custom_example3`. |
| solver#14 | outStanding trains have no deadline in the cost function, so plans over-run the scenario horizon for free. Produces the plan that trips evaluator#6. |
| evaluator#6 | `EvaluatePlan` spins when the plan still has actions but the state is terminal, reporting the symptom rather than "plan extends past the horizon". Terminates via a safety valve; blocks nothing, but the diagnostic misleads. Blocks `7t_custom_example1`. |
| evaluator#1 | Invalid JSON for PB parsing fails quietly. On the legacy `--plan_type Evaluator` path only. |
| solver#17 | Solver and evaluator place a combined inStanding train's members at opposite ends of the track, so the solver routes a departing half out of the blocked end and calls the result feasible. Needs a decision on which convention is right, and probably a companion evaluator issue. |
| solver#18 | Solver ignores `standingIndex`, so the order of several standing units on one track is not the one the scenario asked for. Latent in this corpus — every scenario leaves the field null. The evaluator does honour it. |
| solver#19 | Question, not a defect: splitting a train in place costs no shunt move, and nothing prices the personnel it would need. |

None of #17, #18 or #19 blocks the pipeline. #17 needs a combined inStanding
train that gets split, which no fixture has; #18 needs a non-null
`standingIndex`, which no fixture has; #19 is a modelling question.

`6t_custom_example3` and `7t_custom_example1` cannot produce a valid plan
because of the two issues above and are expected to keep failing until they're
fixed — named in `RELEASE_NOTES.md` for the same reason.

---

## Open decisions

### `--plan_type Evaluator`

Surveyed 2026-08-08 so this can be decided on evidence rather than on the name.

`main.cpp` takes `--plan_type Solver|Evaluator`. The two branches read different
plan formats, and the substantive difference is not the format: a `Run` is
**self-contained**, carrying its own scenario (`Plan.cpp:503`), while the Solver
path takes the scenario separately via `--path_scenario`.

The case for retiring it: `run_evaluator.py` always passes `Solver`, nothing in
the pipeline uses it, and it has no test — the only one that ever named it was
`EngineTest`'s "Plan test", deleted 2026-08-07, which had never passed.

It is also the sole remaining consumer of the legacy input shapes, and therefore
the reason several cleanups stopped short: `Plan.proto` still declares
`trainUnitIds` as `repeated string`, `Train.cpp` keeps its `"****"` placeholder
and `stoi()` guards, and `TrainUnitType::types` is still the string-keyed map
(`Train.h:15`) alongside the HIP path's `typesByPrefixAndCarriages`.

**Retiring it does not delete `Scenario.proto` and `Run.proto`**, which an
earlier draft claimed. The same formats are still *written*, from Python:
`RunResult::SerializeToFile` produces a `PBRun` and is bound in `pyTORS`
(`module.cpp:429`). The reader and that writer are two halves of one round trip.

So the decision is three:

1. Is the self-contained `Run` format wanted at all — as Python output, an
   archive format, a way to replay an evaluation?
2. If yes, does it need a *reader*, or is writing enough? Only the reader is
   `--plan_type Evaluator`; only the reader blocks the cleanups above.
3. If wanted in full, it needs a fixture and a test. It has neither, which is how
   it came to be forgotten.

Not a question CI can settle: nobody here has run that mode. Whoever knows why
the Python bindings exist should decide.

### Where the exported schemas should live — decided, not yet implemented

Tracked in [generator#14](https://github.com/Robust-Rail-NL/robust-rail-generator/issues/14).

`validate-fixtures.yml` clones `robust-rail-generator` and reads `schema/` from
the branch of the same name. Vendoring a copy here would be worse — a stale
schema does not fail, it passes, having checked the wrong contract — so the
workflow also re-exports the schemas in that checkout and gates on them matching
what is committed there.

The branch guess has already produced one false reading: pinned to `pydantic`, a
run validated newly migrated fixtures against the pre-migration schema and
reported 2/18 for a tree really at 10/18, while the freshness gate stayed green
because that schema was perfectly consistent with the wrong models.

**Decided 2026-08-20, on a collaborator's suggestion: move `src/models/` out of
the generator and into this repo.** Not a schema-hosting tweak — the models
themselves relocate, and the generator becomes a consumer of a package published
from here rather than the other way round. The rationale is ownership, not
mechanics: the generator produces `location.json` and `scenario_*.json`, never
a plan, yet its models package currently owns `Plan` too; the configs
(`scenario_config_*.json`) already live under this repo's `Location_*/` and are
the one input in the pipeline that's hand-written rather than generated.

The move is the whole `src/models/` directory — `location.py`, `scenario.py`,
`plan.py`, `scenario_config.py`, `utilities.py` — as one package, since `Plan`
embeds types from `location.py`/`scenario.py` and cannot move alone. Inside the
generator, only 3 files touch any of it (`check_config.py`,
`random_generator.py`, `scenario.py`), which become imports from the new
external package instead. `scripts/export_schema.py` moves here wholesale.

This **replaces** the branch-matching clone in `validate-fixtures.yml` rather
than just fixing it: once the models live here, the exported schema is direct
build output, not a copy of anything, so there is nothing left to go stale
against.

**Deliberately post-2.0.0.** Needs its own pass: packaging this repo as an
installable dependency (doesn't exist today), a pin/lockfile discipline in the
generator's build matching the Docker-tag pinning already in force, and a
decision on distribution mechanism (git dependency vs. a published package).

### Planner plans are not yet valid, and planner/solver output collides

`run_planner.py` works: the image plans `Location_SimpleService` into a plan
that validates against `schema_plan.json` with zero errors, and the evaluator
parses and executes it. The format contract holds end to end.

**The plans themselves are not valid solutions yet**, for two reasons that are
the planning-approach (now robust-rail-planner) team's, not the schema's:

- The evaluator rejects the SimpleService plan with *"Facility 22 is not
  available from 1500 to 2000"*. No converter reads `timeWindow`, so the PDDL
  model cannot respect facility availability. Note the location declares no
  `timeWindow` on that facility at all, so the evaluator is applying a default
  from somewhere — worth establishing where before modelling it.
- `convert_to_tors` stops emitting actions partway through a plan: the trailing
  move/depart steps produce no `Exit`. Pre-existing and confirmed against
  `new_pipeline_version`'s own converter on its own fixture, so not schema
  drift. Held as a strict `xfail` in `test_main_plan_ends_with_an_exit`.

**Planner and solver are mutually exclusive.** Both write
`plans/plan_<suffix>.json`, and `run_evaluator.py` globs `plans/plan_*.json`, so
running both over one location yields one set of plans from whichever ran last
with nothing able to tell them apart. `run_pipeline.py` rejects the combination
rather than documenting it. Comparing planner and solver output on the same
scenario therefore needs a design — separate output directories, or a variant in
the filename that `run_evaluator.py` and the evaluation naming both understand.

---

## Open loose ends

Things I (LP) noticed and want to write down so we won't forget:

Generator:
- [generator#12](https://github.com/Robust-Rail-NL/robust-rail-generator/issues/12):
  `EvaluatorScenario` and `Scenario` represent the same concept twice —
  `ScenarioGenerator` accumulates into the flat, `Train`-based
  `EvaluatorScenario` shape, then `create_solver_format_scenario()` manually
  converts it, field by field, into the `Scenario` shape actually written to
  `scenario_*.json`. Kept in sync by hand, not by construction. Already
  tracked as "Next steps" item 6 in `unified-schema-design.md`; purely
  internal to the generator, doesn't touch the interchange schema.

Solver / HIP:
- The "merge coinciding Wait actions" commit (`e545f33`) seems to have partially
  lost its effectiveness: see differences between current and legacy (1.4.2) plan
  versions.
- `dotnet build` warnings-as-errors is a separate decision; the solver builds with
  two nullable warnings in `Initial/SimpleHeuristic.cs`.
- Rename `ServiceSiteScheduling.NoProto` (`Location.cs`, `Scenario.cs`,
  `Plan.cs`, `InterchangeSchema.cs`, `Utilities.cs` — the records that mirror
  the JSON interchange schema for deserialization). Named for what it isn't,
  a protobuf leftover from the migration. Suggest `Interchange`: matches the
  vocabulary this whole release already uses ("unified interchange schema"),
  and stays clearly distinct from the solver's own internal domain model
  (`Track`, `Train`, `State`, ...) elsewhere in `ServiceSiteScheduling` — bare
  `Model` would collide with that in meaning, not just in name.

Evaluator / TORS:
- ~~See if we can get the Python version of TORS to work?~~ Not worth it; already retired. The Python code in this repo was very outdated. The most recent version of the code lives in [AlgTUDelft/cTORS](https://github.com/AlgTUDelft/cTORS) / [ReubenJ/cTORS](https://github.com/ReubenJ/cTORS).
- **Do a focused session on TORS's own search mode.** TORS does not only replay
  and evaluate a plan; it can also generate one itself, and that looks to be what
  it was originally built for, with plan replay added later.

  This matters beyond curiosity. Nearly every evaluator bug found on 2026-08-07
  was a search-mode primitive behaving wrongly under replay, not a bug in its own
  right:
    - `legal_on_parking_track_rule` rejected a movement ending on a non-parking
      track. Harmless for the search, which emits step-by-step moves the rule
      exempts; fatal for replay, where every movement is a `MultiMove` and a
      departure's last movement lands on the gateway.
    - `Wait` runs until the next queued event. Correct for the search, which has
      no plan and re-decides at every event; wrong for replay, where it discards
      the duration the plan supplied.
    - `ArriveActionGenerator` hardcodes a zero duration, so a plan cannot express
      a train occupying the gateway while it waits for a route in (solver#13).
    - `out_correct_time_rule` demanded an exact departure time that an outStanding
      request (time 0) could never satisfy.

  The two modes share primitives whose contracts hold in only one of them. A
  survey of where else that is true would probably predict the next round of bugs
  rather than waiting to trip over them.

---

## Cleanup pending

- **Retire the `legacy` `--version` choice outright.** It stopped working once
  Phase 1 moved these scripts to the unified format unconditionally; kept
  around as a documented dead end rather than removed. Still an open call.

---

## In progress: `stable`/`edge` channels for the solver image

Started 2026-08-26/27, not part of the 2.0.0 record above. A `stable`/`edge`
channel model for the HIP solver image, so a fix can be published and run
before it's gone through PR review into `main`:

- Solver: new `edge` branch, `CONTRIBUTING.md` documenting the model, and
  `docker-push-edge.sh` (tags `<release>-edge+<date>.<short-sha>`, floats
  `hip:edge`).
- This repo: `run_*.py --version stable|edge` (renamed from `2.0.0`/
  `2.0.0-assert`; `edge` only has real meaning for the solver, the other
  tools resolve it to their `stable` image) and `docker_utils.pull_flag()` —
  `--pull always` for registry tags, so a floating tag like `:edge` is never
  served stale from a local cache.

Not written up anywhere longer-form than the git history itself; worth its
own doc if it grows more channels or more repos.

---

## Reference: decisions still in force

Not open items — these constrain anything built on the schema, so they're
kept here rather than in the history file for anyone starting new work.

| Decision | Resolution |
|---|---|
| `TrainUnitType.reversalDuration` | Computed from `backNormTime`/`backAdditionTime`; off the wire, derived locally |
| Type identity | `(typePrefix, carriages)`, not a combined `displayName` string. Consumers key on the pair |
| `TaskSpec.priority` | Renamed to `optional: bool` — TORS only ever used it as a 0/non-zero flag |
| `Resource` | `{ "kind": "trackPart"\|"facility"\|"staff", "id": <int> }`; `name` dropped; evaluator hard-errors on an unrecognised `kind` |
| `trainUnitTypes` | Stays on `Scenario`, referenced from `TrainUnit` |
| `Plan.trackParts` | Dropped — TORS loads infrastructure from `--path_location` |
| `schemaVersion` | One shared monotonic integer across `Location`, `Scenario` and `Plan`, starting at 1; all bump together |
| Version mismatch | **Warn and continue.** Never a hard reject. Each tool holds `EXPECTED_SCHEMA_VERSION` locally; `SCHEMA_CHANGELOG.md` in the generator records each bump |
| Every id | An `int`, including the composite ones |
| Arrays of IDs | Always end in `IDs` — `memberIDs`, `parentIDs`, `relatedTrackPartIDs`. `IncomingTrain.members` and `Train.members` keep their names because they really do embed their units |
| Retired proto fields | `reserved`, never freed, so a later field cannot inherit a number and meet an old message carrying the old meaning |

**Two traps worth keeping.**

*The proto names lie about which file is live.* Each of the three inputs uses a
different family, and the family called legacy is simultaneously the engine's
internal representation:

| proto | what it actually is |
|---|---|
| `Location.proto` | **live input** — `location.json` parses into `proto_tors::Location`, *not* anything HIP |
| `HIP_Scenario.proto` | **live input** — `scenario.json` |
| `HIP_Plan.proto` | **live input** — `plan.json` under `--plan_type Solver` |
| `HIP_Common.proto` | **live** — shared by the two above |
| `Plan.proto`, `PartialOrderSchedule.proto` | engine internal representation, *and* an input under `--plan_type Evaluator` |
| `Scenario.proto`, `Run.proto` | reachable **only** under `--plan_type Evaluator` |

Anyone reasoning from the names picks the wrong file — which happened during
Phase 3e, when a rename went into `HIP_Location.proto` and the compiler pointed
out the live path reads `proto_tors::Facility`.

*Protobuf cannot express an absent list.* `trainUnitIds` was documented as "if
not specified, all train units are involved". That contract was never
expressible: `repeated` fields carry no presence information, so absent, `null`
and `[]` all arrive as the same empty field. Anything reintroducing an optional
list needs a deliberate design for presence, not just the field back.

---

See [`roadmap-2.0.0-history.md`](roadmap-2.0.0-history.md) for the branch
naming rationale, the rc-by-rc verification log, and the full "what was done"
table.
