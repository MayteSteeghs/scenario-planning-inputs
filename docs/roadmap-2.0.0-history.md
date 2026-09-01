# 2.0.0 release — history

Split out of `docs/roadmap-2.0.0.md` on 2026-08-27, once that file's open
items had shrunk enough that this narrative — every rc cut, every
re-verification run, every resolved decision — was crowding them out. Nothing
here is expected to change or to gate anything; it is kept as a single
greppable record rather than relying on `git log -p docs/roadmap-2.0.0.md`
alone. See [`roadmap-2.0.0.md`](roadmap-2.0.0.md) for what's still open.

---

## Branch naming

All five repos shared one integration branch, **`release/2.0.0`**, merged into
each repo's stable branch and deleted when 2.0.0 shipped. Renamed 2026-08-08
from `pydantic` (generator, scenario-planning-inputs), `noproto` (solver,
evaluator) and `new_schemas` (planning-approach) — each named for an
implementation detail rather than the goal, and differing per repo.

The shared name was not only tidiness. `validate-fixtures.yml` read the
generator's schemas from the branch of the same name, so that a coordinated
schema change was validated against its own schema rather than the base
branch's. That only worked when the name matched everywhere.

References to the old names in git history are correct as written: that is
where the work happened at the time.

---

## rc.4 (generator) / rc.3 (hip, tors) — cut and verified

`rc.2` was the last point where all three tool repos shared one nameable rc
number. Two more schema-adjacent changes landed after it, and — unlike
`standingIndex`'s narrowing — both actually touched the committed fixture
corpus in this repo:

- **`rc.3`** (generator, hip, tors): `reversalDuration` and
  `canDepartFromAnyTrack` dropped from the wire format entirely (see
  generator's `SCHEMA_CHANGELOG.md`, "Unversioned — 2026-08-21"). Traced as
  dead in all three repos — hip and tors needed no code change, but both got
  matching `rc.3` tags anyway to keep every repo's version aligned with the
  schema change, plus the inert DTO/fixture cleanup commits already made on
  each. Because the fields are *removed*, not narrowed, `extra="forbid"`
  meant every fixture still carrying either key (all null-valued) started
  failing validation — 71 files across this repo needed the two keys
  stripped, a mechanical, value-preserving edit.
- **`rc.4`** (generator only): every generated JSON file now ends with a
  trailing newline, matching what `scripts/export_schema.py` already did.
  Pure formatting — no consumer's JSON parsing is affected — so hip and tors
  stay on `rc.3`. 60 checked-in fixture files needed the same trailing
  newline appended by hand, since the pipeline only regenerates
  `scenarios/`, not `fixtures/`.

Both re-run against published images with results matching the `rc.2`
baseline exactly (counts, exit codes, `.err` content) — see [Re-verified on
`2.0.0-rc.3`](#re-verified-on-200-rc3) and [Re-verified on
`2.0.0-rc.4`](#re-verified-on-200-rc4) below.

### What solver#11 turned out to be

The same `State` was departed twice, but not by the same task. `ComputeLocation`
treats a routing that ends on the track it started from as "nothing moved": the
next task takes over the previous task's `State` rather than departing and
re-arriving, which keeps the train's place in the occupation and is what makes
switching a task onto the from-track worth proposing at all.

That shortcut only works one-to-one. When such a routing is a **split**, every
one of its parts was given the same `State`, so each later removed the same deque
node and the second found it gone. `ParkingSwitchMove`/`ParkingSwapMove` create
the configuration by relocating a split's halves onto the routing's own
from-track.

The seed parity — 2/4/6/8/10/12 crash, odd ones pass — was the thread we expected
to pull hardest and turned out to be shallow: splits-in-place occur on exactly the
even seeds. Seed 1 runs 86,370 `ComputeModel` passes without one.

Two defects, fixed separately: the aliased `State`, and a serialisation crash it
uncovered (a routing's duration covers a split's decoupling as well as its
travel, so an in-place split emitted a Move action with an empty path). Then
modelled properly: the parts now take over the stretch the whole train held
rather than being departed and re-arrived at the end of the track, which had
understated the crossings they would later owe to get out.

`Tests/TestData/scenario_inplace_split.json` in the solver reproduces it
deterministically at seed 1 in under a second, replacing the thirty-second seed
sweep, and fails against both pre-fix states for the right reasons.

Full brief in solver#11's comments.

---

## Resolved decisions

### Renaming this repo to `robust-rail-general` — resolved 2026-08-26

Done, post-2.0.0 as planned. Checked what would actually break, across all four
sibling repos, before treating it as a git-settings change:

- **Load-bearing, would break outright:** `robust-rail-generator/src/main.py`
  and `src/example.py` default `--path` to a sibling directory literally named
  `scenario-planning-inputs`. `planning-approach/.github/workflows/schema.yml`
  clones this repo by that name, mounts it at `/siblings/scenario-planning-inputs`,
  and sets `RRN_INPUTS_DIR` to match — all three spots have to move together, or
  its CI breaks. `planning-approach/tests/test_plan_schema.py` makes the same
  sibling-directory assumption locally (`_sibling("scenario-planning-inputs",
  "RRN_INPUTS_DIR")`), overridable by the env var but not by default.
- **Present but not load-bearing:** `robust-rail-solver`'s
  `config_standard.yaml`/`config_simple_service.yaml` and
  `robust-rail-evaluator/data/Bugs/*/config_solver.yaml` hardcode
  `/workspace/scenario-planning-inputs/...` paths, but nothing in either
  repo's CI references them by name — manual/local-dev config, and already
  stale regardless (pre-unification `location_solver.json`/
  `scenario_solver.json` layout, removed in Phase 1).
- **Cosmetic only, safe to sweep separately:** READMEs, `SCHEMA_CHANGELOG.md`,
  `RELEASE_NOTES.md`, `unified-schema-design.md` and similar docs/comments
  across generator, evaluator and planning-approach. Not fully inventoried —
  `planning-approach/plan_visualizer/*.py` and
  `convert_to_pddl/**/convert.py` also matched a search for the name and
  weren't individually checked.
- **Not code:** GitHub redirects the old repo URL (web, clone, fetch/push)
  as long as nobody claims `scenario-planning-inputs` afterward, so PR links
  already shared keep working. Existing local clones should still get
  `git remote set-url origin <new-url>` explicitly rather than rely on that.

Sequenced as planned: `gh repo rename` first (old URL redirects), then the
local clone's remote and directory, then the load-bearing fixes in the same
pass — `robust-rail-generator`'s `src/main.py`/`src/example.py` default
`--path`, and `planning-approach`'s `schema.yml`, `test_plan_schema.py`, plus
the forward-looking doc/comment references in both repos (`README.md`,
`SCHEMA_STATUS.md`, `pytest.ini`, `docker-entrypoint.sh`, `conftest.py`). The
"present but not load-bearing" hardcoded paths above, and comments already
phrased as historical ("this used to..." in the `convert_to_pddl` variants,
`archive/`), were left alone — not broken by the rename, and rewriting them
would blur what's current from what's a record of the past.

`planning-approach` itself was renamed to `robust-rail-planner` the following
day, 2026-08-27, by the same logic.

### ~~`planning-approach/pipeline.py`~~ — resolved 2026-08-10

Deleted, along with `run.py`, `cli.py`, `evaluate.py` and `generate.py`, by
`new_pipeline_version`'s Docker-first restructure, which was merged into
`release/2.0.0` on 2026-08-10. The batch-driver role it played belongs to this
repo's `run_planner.py` / `run_evaluator.py` now, so the design question it
posed no longer needs answering.

Note what went with it and has **no** replacement: `src/local_search/solve.py`
and `src/plan/audit_discrete_plan.py`. Recoverable from
`git show 7c0346e:<path>`; recorded in `planning-approach/SCHEMA_STATUS.md`.

---

## Resolved loose ends

Generator, from the "Open — loose ends" list that used to live in the main
roadmap file:

- ~~Clean up the generator's README.md: it has a TODO that should be dealt
  with~~ Done — no TODOs left; setup instructions now match reality (`uv
  sync`, `uv run`) instead of the conda-based world that predated
  `pyproject.toml`.
- ~~Figure out what to do with the regression-baseline files in the generator
  repo (just delete?). See also `src/generate-scenarios.sh`.~~ Done — both
  gone; existed only to support the protobuf-to-Pydantic migration itself.
- ~~Clean up the generator repo: automated formatting with pre-commit, Ruff
  etc.~~ Done — `.pre-commit-config.yaml` and a CI job enforce it.
- ~~Decide what to do with `unified-schema-design.md`. At least remove
  in-progress bits?~~ Done — marked `**Status: historical.**`, the migration
  it planned is this release.
- ~~Default scenario filename truncated the config name to its last
  underscore-token~~ — fixed on `generator@2d086f0`, shipped in `rc.1`
  (moved tag). `sweep_seeds.py`'s matching `base` formula updated alongside
  (`5911f1b`). `feasible_small`/`marginal_congestion`/`marginal_length` and
  the two `random_distribution*` fixtures were renamed to their un-truncated
  names as a result (`3fac5cb`).
- ~~Make sure the planner can also speak the new schema~~ Superseded — the
  planner step went live and the format contract holds end to end (the image
  plans `Location_SimpleService` into output that validates against
  `schema_plan.json` with zero errors, and the evaluator parses and executes
  it). What's still open from there — the plans it produces aren't valid
  solutions yet, and planner/solver output collides — is tracked in the main
  roadmap file's open decisions, not here.

---

## Release evidence

### The `2.0.0-beta.3` run (2026-08-09)

The first end-to-end run against **published** images since 2026-08-02, and the
first at all since every id became an int and three fields were renamed and four
deleted. Everything in between was checked by schema validation and unit tests,
which establish that the files are well formed and that each tool parses them
alone — not that the three agree at runtime.

11 scenarios: the 8 canonical plus the three configurations added 2026-08-07.
Generator 11/11, solver 11/11, evaluator 8/11 exit-0. Whole pipeline: 2m20s.

| Scenario | Verdict |
|---|---|
| `4t_random_1s_small` | **valid** |
| `2t_random_1s_length` | **valid** |
| `8t_custom_example2` | **valid** — was rejected on 2026-08-02 |
| `10t_random_42s_distribution1` | infeasible: arrival train 270.62 m > track 15's 255 m |
| `10t_random_42s_distribution2` | infeasible: departure train 270.62 m > track 15's 255 m |
| `48t_custom_larger-example` | infeasible: arrival train 1006 324.12 m > 255 m |
| `14t_random_1s_congestion` | not valid: adding SU-12 to 906b exceeds 255 m |
| `6t_custom_example3` | not valid: parking not allowed on 906a (solver#13) |
| `7t_custom_example1` | not valid: no-progress guard at T4800 (solver#14 + evaluator#6) |
| `30t_random_98s_test` | not valid |
| `simple_service_4t_custom_late` | not valid |

**`example2` moved from rejected to valid** — the clearest evidence the
2026-08-07 replay fixes were worth making.

**The assert pass agrees.** Re-evaluating the same plans with
`--version 2.0.0-assert`, which differs from `2.0.0` in exactly one image,
gave identical verdicts on all 11 and 26 of 27 byte-identical output files; the
twenty-seventh differs only in `docker pull` chatter. No assertion fired.

The second pass must be `--steps evaluator`: re-solving would produce its own
plans and the diff would compare two unrelated things.

**The solver is deterministic run-to-run.** Four consecutive runs produced
byte-identical plans for all 11 scenarios. A wall-clock-bounded local search
would not normally be reproducible; it is here because `StopWhenFeasible: true`
means these searches terminate on a condition and none comes near the 3600 s
budget. That guarantee is conditional — it would not hold for a scenario hard
enough to exhaust the budget.

**Regenerated scenarios are semantically identical to the committed ones**, all
differences being key order (`id` moved to the front) with equal parsed content.

### Re-verified on `hip:2.0.0-beta.4`

The solver moved to beta.4 for `641e380`. Re-ran the whole pipeline: all eleven
plans byte-identical, all eleven verdicts unchanged. That commit is inert on
healthy paths.

The generator and evaluator stay at beta.3, which is correct rather than an
oversight — neither repo's compiled source changed after its beta.3 tag. Versions
here are per-repo, not a release train, and the `--version` key names a pipeline
configuration rather than a shared version number.

`beta.3` was deliberately **not** re-tagged onto the newer commit. Those images
produced the evidence above, and moving a published tag would make it
unreproducible.

**The warning that used to be here has been settled by measurement, in the
cheap direction.** It said a solver#11 fix would change what the parking model
computes, so plans could legitimately differ and the fixtures might need
regenerating rather than re-confirming.

Measured over all 10 KleineBinckhorst scenarios at seeds 1-6, solver and
evaluator, before and after the fix: **57 of 57 plans byte-identical, no verdict
changed.** The only difference is that the three runs that previously crashed now
produce a plan. The fix does change the parking model, but only on a
configuration — a split that stays on its own track — that healthy runs never
reach, which is the same reason the crash only ever appeared on even seeds.

So re-verification was expected to be a formality, with two caveats: the sweep
used a local assertions build at `MaxDuration: 15` rather than the published
image at the pipeline's `3600`, and it covered KleineBinckhorst only. Both are
now closed by the beta.5 run below, which used the published image at the full
budget and included SimpleService.

### Re-verified on `hip:2.0.0-beta.5`

The solver moved to beta.5 for the solver#11 fix (`6317d8e`, `82c825f`,
`87a48c9`, `5a4a7f8`, `2bd3bf2`) and `f99438c` (solver#16). Re-ran the whole
pipeline on 2026-08-10, generator through evaluator, 2m05s:

- Generator 11/11, solver 11/11, evaluator 8/11 exit-0 — the same counts as
  beta.3 and beta.4.
- **All 11 plans byte-identical** to the beta.4 run, and **all 11 evaluation
  outputs byte-identical** too. Not just the same verdicts: the same bytes.
- Regenerated scenarios again differ from the committed ones only in key order,
  parsing equal on all 8 that the generator rewrites.

This is the outcome the seed sweep predicted, now at the pipeline's own budget
and covering both locations. The fix changes the parking model only on a
configuration healthy runs never reach.

The generator and evaluator stay at beta.3 for the same per-repo reason as
before; neither repo's source has changed since.

Not yet covered: the assert pass. `hip:2.0.0-beta.5-assert` was still building
when this ran, so the run above is the plain image only. No assertion has been
exercised against the fix outside the solver's own tests.

### Re-verified on `2.0.0-rc.1`

All five repos tagged `2.0.0-rc.1`, this repo's `--version` selectors repointed
(`7989c59`), and the pipeline re-run on 2026-08-11 against the published
non-assert images (`generator:2.0.0-rc.1`, `hip:2.0.0-rc.1`,
`tors:2.0.0-rc.1`), 2m06s:

- Same counts as every prior run: generator 11/11, solver 11/11, evaluator
  8/11 exit-0.
- **Every plan in the committed fixture set is byte-identical** to the
  beta.5 run. The three non-fixture scenarios added 2026-08-07
  (`14t_random_1s_congestion`, `2t_random_1s_length`, `4t_random_1s_small`)
  aren't in git to diff against, but their solver/evaluator exit codes match.
- The one stderr size change (`distribution1`, 2 lines → 32) is `docker pull`
  chatter from the first pull of the new tag, not a content difference — the
  same kind of noise the beta.3 evidence already called out.

`hip:2.0.0-rc.1-assert` is published; `tors:2.0.0-rc.1-assert` is still
building, so the assert pass is the one thing this run does not cover.

**Assert pass, 2026-08-11.** `tors:2.0.0-rc.1-assert` published; re-ran
`--version 2.0.0-assert --steps evaluator` against the plans already on disk
(re-solving would produce different plans and the diff would compare two
unrelated things). All 11 evaluation outputs byte-identical to the plain
`tors:2.0.0-rc.1` pass — same 8/11 exit-0 pattern, no assertion fired.

**The rc.1 gate is now fully closed**: every image is published, the pipeline
has run against all of them, plain and assert agree, and every fixture plan
matches beta.5. (Superseded by `rc.2`, below — this entry stays as the record
of how `rc.1` itself was closed.)

### Re-verified on `2.0.0-rc.2`

`rc.2` across generator, hip and tors carries the `standingIndex:
Optional[float] -> Optional[NonNegativeInt]` change (see
`SCHEMA_CHANGELOG.md`'s "Unversioned — 2026-08-19" entry) and the new
standing-order consistency check. Re-verified in two steps as each image
landed:

- **Generator + solver**, once `hip:2.0.0-rc.2` was published: full
  `--steps generator,solver` run, all 11 canonical scenario/plan pairs
  byte-identical to the committed baseline. Expected — every fixture already
  has `standingIndex: null`, so the type narrowing is a no-op on the wire, and
  the solver's own change (`?? 0.0` → `?? 0` in `ProblemInstance.cs`) doesn't
  observably affect output either.
- **Evaluator**, once `tors:2.0.0-rc.2` was published: ran against the same
  plans. `docker inspect` showed `rc.1` and `rc.2` are genuinely different
  image digests (a real rebuild, not a re-tag), so this wasn't assumed safe —
  re-ran the same plans against `tors:2.0.0-rc.1` for comparison and diffed
  all 11 canonical `.txt` outputs: byte-identical. Confirms the changelog's
  claim that the evaluator needed no code change, in the actual output, not
  just the source diff.

**Assert pass, 2026-08-20.** `tors:2.0.0-rc.2-assert` published; re-ran the
same plans against it. All 11 canonical evaluations byte-identical to the
plain `rc.2` pass — no assertion fired. `rc.2` is now verified as fully as
`rc.1` was: generator, solver and evaluator all checked, plain and assert.

### Re-verified on `2.0.0-rc.3`

`rc.3` drops `reversalDuration`/`canDepartFromAnyTrack` (see [rc.4
(generator) / rc.3 (hip, tors) — cut and verified](#rc4-generator--rc3-hip-tors--cut-and-verified)
above). Verified in two passes, adopting a faster method for the first time: build a
native-arch image locally and validate with it before the slow multi-arch
push, rather than waiting on the push to check anything.

- **Fast local pass**: a plain (no `buildx`, no QEMU) `docker build` of
  `tors:2.0.0-rc.3` finished in a couple of minutes, versus 20+ for the real
  multi-arch push. Ran the evaluator against it on all 11 canonical plans:
  exit codes and `.err` content byte-identical to the `rc.2` baseline; the
  `.txt` trace files differ only by a **set-equal reordering** (same lines,
  different order — confirmed by sorting both sides) of route/movement
  listings. Running the same local binary twice back-to-back gave a 0-diff,
  so the reordering is stable within a build but shifts between builds — see
  "Why the evaluator's `.txt` output can reorder across builds" below.
- **Published multi-arch images**: once `hip:2.0.0-rc.3` and
  `tors:2.0.0-rc.3(-assert)` were pushed, re-ran the full
  `generator->solver->evaluator` pipeline against them: same counts as every
  prior run (11/11, 11/11, 8/11 exit-0, same three known-infeasible
  scenarios). A plain-vs-assert comparison on `rc.3` showed identical `.err`
  and exit codes, set-equal `.txt`, across all 10 KleineBinckhorst scenarios.

**Why the evaluator's `.txt` output can reorder across builds.** cTORS mixes
content-hashed and pointer-hashed `unordered_map`s keyed by `ShuntingUnit*`.
Most (e.g. `State::shuntingUnitStates`) use a custom ID-based hash, stable
across builds; at least one (`MoveHelper.cpp`'s `visitedNeighbors`) has no
custom hash and falls back to the default pointer hash, whose bucket order
depends on heap addresses — which shift whenever anything upstream changes
allocation size, e.g. regenerating protobuf code after a `.proto` field is
removed. Cosmetic, not a correctness regression: the `.err` output and exit
codes, which is what the pipeline and CI actually gate on, are untouched.
Treat any future `.txt`-only diff the same way — sort-compare before
assuming a regression.

### Re-verified on `2.0.0-rc.4`

`rc.4` is generator-only (trailing newline after every generated JSON file,
see above); hip and tors stay pinned to `rc.3`. Ran the full pipeline against
`generator:2.0.0-rc.4` + the existing `rc.2` solver/evaluator images first
(counts matched exactly, `.txt`/`.out` diffs were the same
build-reordering/version-banner pattern as `rc.3`'s, `.err` untouched), then
again after the `rc.3` solver/evaluator pins landed, with the same result.
2026-08-21.

### What these runs do not cover

- x86-64 only. arm64 is covered at the unit-test level (evaluator and solver CI
  matrices, 2026-08-09) but the pipeline has never run there. A cross-arch
  comparison would not be meaningful anyway — different machine, and the
  determinism guarantee is conditional on not exhausting the time budget.
- Only `Seed: 1`. That is why solver#11 never fired here even before the fix:
  the triggering configuration does not arise on that seed at all. The pipeline
  exercises one path through the search per scenario, not the search's range —
  the seed sweep in the solver repo is what covers that.

---

## Phase 4 — Stable release (complete)

PRs opened in all four repos sharing the interchange format (`planning-approach`
deliberately excluded — not ready), `release/2.0.0` into each stable branch:
[generator#11](https://github.com/Robust-Rail-NL/robust-rail-generator/pull/11),
[solver#20](https://github.com/Robust-Rail-NL/robust-rail-solver/pull/20),
[evaluator#7](https://github.com/Robust-Rail-NL/robust-rail-evaluator/pull/7),
[this repo#8](https://github.com/Robust-Rail-NL/scenario-planning-inputs/pull/8).
Opened as drafts, not for line-by-line review of a months-long migration diff —
a coordination point and a CI run against the real merge target.

- ~~Write the release notes.~~ Done 2026-08-20: `RELEASE_NOTES.md` now exists
  in all four repos. This one names solver#13, solver#14 and evaluator#6, and
  the two fixtures they permanently block (`6t_custom_example3`,
  `7t_custom_example1`) — otherwise "integration tests pass" reads as more
  true than it is.
- ~~Update this repo's `README.md`.~~ Done 2026-08-20: rewritten for the
  single-file pipeline, historical two-file framing dropped rather than
  footnoted.
- ~~`--version` now defaults to `2.0.0` instead of `legacy`~~ Done 2026-08-20 —
  `legacy` stopped working once Phase 1 moved these scripts to the unified
  format unconditionally, so a default that reliably failed wasn't worth
  keeping. (The `*-protobuf`/`*-pydantic` comparison directories were never
  committed — local scratch output only, deleted 2026-08-10. The comparison
  they produced is recorded in this file's git history, not in the files
  themselves.) `--version` was later renamed `2.0.0` → `stable`, 2026-08-26 —
  see the main roadmap file's post-2.0.0 note.
- ~~Mark the four PRs ready~~ Done 2026-08-21: all four `draft=false`,
  `state=OPEN`. solver#20 targeted `main` directly rather than `dev`
  (retargeted 2026-08-21, before any review — see `CLAUDE.md`):
  `release/2.0.0` already contained `dev`'s full history, so that one merge
  covered both without a separate promotion. `dev` itself was updated by hand,
  outside this release's merge sequence.
- ~~Merge all four, then delete `release/2.0.0` in each~~ Done. Merged
  generator, solver, evaluator and planner first (2026-08-14 through
  2026-08-21), this repo's #8 last (2026-08-24) since it had the `CLAUDE.md`
  conflict the note above flagged. `release/2.0.0` deleted afterward in
  solver, evaluator, planner and this repo. Generator's copy was left behind
  as a stale-but-fully-merged branch — see the cleanup item in the main
  roadmap file.
- ~~Tag `generator:2.0.0`, `hip:2.0.0`, `tors:2.0.0` by re-tagging the
  verified rc digests~~ Done 2026-08-21 (a second time — the first tagging,
  against `rc.2`, went stale once `rc.3`/`rc.4` landed). Used `docker buildx
  imagetools create` to copy the multi-arch manifest list directly on the
  registry rather than pull/rebuild, so the re-tag can't drift from the
  source even for generator's amd64+arm64 index; confirmed by digest against
  `generator:2.0.0-rc.4` and `hip:2.0.0-rc.3`/`tors:2.0.0-rc.3`. `:latest`
  moved alongside in all three, also confirmed by digest.

---

## Settled — what was done

Full detail in git history; commit ranges given where they help.

| Phase | Outcome |
|---|---|
| 0 — Design decisions | All eight resolved; results in the decisions table in the main roadmap file |
| 1a — `schemaVersion` | Implemented in all three tools plus fixtures |
| 1 — Scenario unification | One `scenario_*.json` per case in HIP field names; `scenario_solver_*.json` retired; `location_unified.json` → `location.json`. Solver retired `DeepLook`, `Converter.cs` and every protobuf-shaped class; evaluator migrated its read path and simplified the service-task rules |
| 2 — Generator cleanup | protobuf dependency dropped; `typePrefix`/`carriages` identity; `optional: bool`; PascalCase enums; JSON Schema exported |
| 3 — Integration testing | Parity established against the protobuf baseline (6/8 byte-identical, 2/8 same verdict); three evaluator crash bugs found and fixed along the way |
| 3c — CI | All five repos gate on push and PR. Generator `pytest` + schema freshness; solver `csharpier`, build, smoke run, 35 tests; evaluator `ctest` 7/7; this repo's fixture validation; planning-approach schema tests. arm64 matrices added 2026-08-09 for the two compiled repos |
| 3d — Every id an int | Across all three repos and every fixture. Removed four `stoi()` calls from cTORS and fixed a latent sort bug where `ShuntingUnit.Id` sorted unit 10 before unit 2 |
| 3e — Naming convention | `*IDs` everywhere; `Action.trainUnitIds`, `ShuntingUnit.standingType` and `Plan.trackParts` deleted as written-by-nobody and read-by-nobody; the `Park` task type turned out unreachable |
| 3f — Proto layout | `HIP_Location.proto` held four unreachable messages; removed and renamed to `HIP_Common.proto`. The rest is blocked on the `--plan_type Evaluator` decision |
| 3g — planning-approach | Converter now writes plans the schema accepts (269 validation errors to 0); `standingType` translated to the `StandIn`/`StandOut` task types rather than deleted; first tests and CI added. `pipeline.py` resolved separately, above |
| Fixture corpus | `sweep_seeds.py --save` writes a classified corpus under `Location_*/fixtures/{feasible,infeasible,unresolved}/`; all of it validated by `validate_json.py`, which CI gates on |
