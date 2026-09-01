# Release notes

## 2.0.0 — 2026-08-20

This repo's slice of the shared 2.0.0 release: the same interchange format,
tagged together, across `robust-rail-generator`, `robust-rail-solver` (HIP) and
`robust-rail-evaluator` (TORS). This repo is the integration harness — the
pipeline scripts, the fixture corpus, and the location data those tools run
against. The full cross-repo picture — verification evidence, what each repo
changed, and the decisions behind the schema — lives in
[`docs/roadmap-2.0.0.md`](docs/roadmap-2.0.0.md).

### One file per artifact, not two

`location_solver.json` and `scenario_solver_*.json` are gone. Every location,
scenario and plan is now a single file in the unified interchange format,
consumed by all three tools directly:

- `location_unified.json` was renamed to `location.json`
- `run_solver.py` reads `scenario_*.json` instead of `scenario_solver_*.json`
- `run_planner.py` reads `location.json` instead of `location_solver.json`

`README.md` has been rewritten to match; it previously still documented the
two-file world.

### Known limitation: two canonical fixtures can't produce a valid plan

`6t_custom_example3` and `7t_custom_example1` are expected to fail downstream,
not because of anything in this repo's data, but because of open issues in the
tools that consume it:

- `6t_custom_example3`: the solver parks on a non-parking arrival track when it
  can't move into the yard immediately (`solver#13`).
- `7t_custom_example1`: the solver's cost function has no deadline for
  outStanding trains, so it produces a plan that overruns the scenario
  horizon for free, which then trips a diagnostic-quality bug in the
  evaluator's terminal-state handling rather than a clean failure
  (`solver#14`, `evaluator#6`).

Both were deferred deliberately rather than blocking 2.0.0. If you're running
the full pipeline and see these two fail, this is why.

### Fixture corpus and validation

`sweep_seeds.py --save` classifies a configuration's outcomes across a range
of seeds into `Location_*/fixtures/{feasible,infeasible,unresolved}/`.
`.github/workflows/validate-fixtures.yml` gates every push and PR on
`validate_json.py` against the JSON Schema `robust-rail-generator` exports
from its Pydantic models, itself gated on that schema being fresh relative to
the models — a stale schema doesn't fail validation, it validates against the
wrong contract and passes, which is the failure mode worth guarding against.

That gate is also why two further generator-side changes required edits
across the fixture corpus here, even though neither changes any tool's
runtime behavior. `reversalDuration` and `canDepartFromAnyTrack` are dropped
from the wire format entirely (traced as dead in generator, solver and
evaluator alike — see generator's `SCHEMA_CHANGELOG.md`); because `RailModel`
forbids extra fields, every fixture still carrying either key (all
`null`-valued) failed validation outright, so 71 files had the two keys
stripped. Separately, generated scenario JSON now ends with a trailing
newline; 60 checked-in fixture files that the pipeline doesn't regenerate got
the same newline appended by hand for consistency. Full verification
evidence for both is in `docs/roadmap-2.0.0-history.md`'s
[Release evidence](docs/roadmap-2.0.0-history.md#release-evidence) section.

### Pipeline scripts

`run_pipeline.py` drives `run_generator.py` → `run_solver.py` (or
`run_planner.py`, mutually exclusive with the solver — both write
`plans/plan_<name>.json`) → `run_evaluator.py`, or any subset via `--steps`.
`--version` now defaults to `2.0.0` rather than `legacy`: `legacy` stopped
working once Phase 1 moved these scripts to the unified format
unconditionally, so a default that reliably failed wasn't worth keeping.
`legacy` is still selectable explicitly for anyone doing a protobuf
comparison; retiring it outright is tracked as a follow-up.

### The planner is a live alternative, versioned separately

`run_planner.py` runs `ghcr.io/robust-rail-nl/planner`
(`planning-approach`), an alternative to the solver rather than an addition.
It's versioned independently (`0.1.0`, not `2.0.0`) — that number names the
three repos sharing the interchange format, and the planner's plans aren't
yet valid solutions (two known converter issues, tracked in
`docs/roadmap-2.0.0.md`), so it isn't part of this release train.

### Pre-unification leftovers cleaned up

Top-level `check_location_format.py`, which diffed `location.json` against
`location_solver.json`, is removed — the latter hasn't existed since Phase 1.
`Location_KleineBinckhorst/config_solver.yaml` lost its `LocationPath`/
`ScenarioPath`/`PlanPath` lines, which named that same retired file and were
never actually read (`run_solver.py` regenerates those three paths fresh into
a temp config on every run); the file's `Mode`/`DebugLevel`/`TabuSearch`/
`SimulatedAnnealing` settings are real, active solver-tuning parameters
(`run_solver.py:107`) and stay.
