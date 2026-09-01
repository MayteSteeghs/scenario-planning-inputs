```markdown
## Repository branch awareness

Five repos take part in the 2.0.0 release, and all of them use one shared
integration branch: **`release/2.0.0`**. It is merged into each repo's stable
branch and deleted when 2.0.0 ships.

| Repo | Stable branch | Release branch |
|---|---|---|
| `robust-rail-generator` | `main` | `release/2.0.0` |
| `robust-rail-solver` | `main` | `release/2.0.0` |
| `robust-rail-evaluator` | `main` | `release/2.0.0` |
| `robust-rail-general` (this repo) | `main` | `release/2.0.0` |
| `robust-rail-planner` | `main` | `release/2.0.0` |

Solver is the one repo with two stable-ish branches, `dev` and `main`, and the
one place that needed a deliberate call rather than following the table:
`release/2.0.0`'s PR (solver#20) targets `main` directly, not `dev` — it was
opened against `dev` first, retargeted 2026-08-21 before any review landed.
`release/2.0.0` already contains `dev`'s full history as an ancestor (~25
pre-release commits: version bump, dockerization, arm64 support, refactors —
never promoted to `main`), so merging straight into `main` brings that backlog
along for free; no separate `dev`→`main` promotion needed. `dev` itself is
being updated separately, by hand, outside a PR — not part of this release's
merge sequence.

It was previously a different name per repo — `pydantic`, `noproto`,
`new_schemas` — each named after an implementation detail rather than the goal.
Renamed 2026-08-08. Older commits and docs still refer to the old names when
describing where work happened; those are historical and correct as written.

Run `git branch --show-current` before investigating code or assessing change
impact. On a stable branch you are looking at protobuf-based code; on
`release/2.0.0` at the JSON-schema code.

The shared name is also load-bearing for CI: `validate-fixtures.yml` reads the
generator's schemas from *the branch of the same name*, which only works because
the name is the same everywhere.

## robust-rail-general branch policy

`main` is kept stable for coordination with the separate planner team. It contains
only design decisions (docs, config fixes) that do not break the existing pipeline.

`release/2.0.0` is where all Phase 1 and later implementation work lives:
- `location_unified.json` renamed to `location.json`
- `run_solver.py` reads `scenario_*.json` (unified) instead of `scenario_solver_*.json`
- `run_planner.py` reads `location.json` instead of `location_solver.json`
- Future: integration test results once solver and evaluator are updated

All Phase 1 and later work in this repo goes on the `release/2.0.0` branch.
```
