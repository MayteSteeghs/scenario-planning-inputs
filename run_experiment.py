#!/usr/bin/env python3
"""Run solver and/or planner against one or all scenarios in a location and
record which instances were solved, for local solver-vs-planner comparison.

Drives run_solver.py / run_planner.py / run_evaluator.py as subprocesses via
their --scenario/--output-dir (and --plan/--scenario) flags. Each
(instance, tool) attempt gets its own directory, named after the search
approach rather than the script that drives it:

  <output-dir>/<instance>/local_search/  plan.json, solver.out/.err, result.json,
                                          eval.out/.err, eval_result.json
  <output-dir>/<instance>/planning/      same layout

--num-seeds N runs the solver N times per instance instead of once, each
seed getting its own local_search/seed<i>/ subdirectory with that same
layout (planning is unaffected -- run_planner.py has no seed concept).
report_results.py/coverage_analysis.py detect and handle both layouts.

result.json (written by run_solver.py/run_planner.py) records whether the
tool produced a plan; eval_result.json (written by run_evaluator.py, only
when a plan was produced) carries the "solved" verdict — solved is decided
by the evaluator alone, never by the solver/planner's own exit code.

Runs run_generator.py over the location first (cheap relative to solving/
planning) so every configurations/scenario_config_*.json has a matching
scenarios/scenario_*.json before instances are resolved. --config-dir
restricts both generation and the instances that follow it to one external
directory of configs, instead of the location's own configurations/.

Finishes by running report_results.py over --output-dir, writing runs.csv and
feasibility.csv there, then coverage_analysis.py, writing
coverage_analysis.txt (RQ1 coverage + Wilson intervals + exact McNemar test,
per the experimental-setup doc) -- both skipped on --dry-run, since a dry
run's results are never fresh.

progress.csv (instance, local_search, planning -- "done"/blank) is rewritten
in --output-dir after every (instance, tool) attempt finishes, whether that
finish came from a real evaluator call or from the tool failing/timing out
before ever reaching one -- a live view of how far a long run has gotten.
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --tools/result.json still say "solver"/"planner" (they name the script/the
# tool field run_solver.py and run_planner.py themselves write), but the
# per-instance output directory is named after the search approach instead.
FOLDER_NAMES = {"solver": "local_search", "planner": "planning"}


# A certification pass is conventionally run at a multiple of the main budget
# (see the experimental-setup doc's "certification runs" protocol), not the
# same T -- so the default threshold isn't just --max-duration itself.
CERTIFY_MULTIPLIER = 6


def _run_report(out_dir: Path, max_duration, certify_threshold) -> None:
    # --certify-threshold, if given directly, wins outright. Otherwise derive
    # it from --max-duration (this invocation's own budget input) rather than
    # an independently-guessed number; report_results.py's own default
    # applies only when neither --max-duration nor --certify-threshold was given.
    if certify_threshold is None and max_duration is not None:
        certify_threshold = CERTIFY_MULTIPLIER * max_duration
    cmd = [
        sys.executable, str(ROOT / "report_results.py"), str(out_dir),
        "--runs-csv", str(out_dir / "runs.csv"),
        "--feasibility-csv", str(out_dir / "feasibility.csv"),
        *(["--certify-threshold", str(certify_threshold)] if certify_threshold is not None else []),
    ]
    subprocess.run(cmd, cwd=ROOT)


def _run_coverage_analysis(out_dir: Path) -> None:
    cmd = [
        sys.executable, str(ROOT / "coverage_analysis.py"), str(out_dir),
        "--output", str(out_dir / "coverage_analysis.txt"),
    ]
    subprocess.run(cmd, cwd=ROOT)


def _run_generator(location: str, version: str, dry_run: bool, config_dir: Path = None) -> None:
    cmd = [
        sys.executable, str(ROOT / "run_generator.py"),
        "--location", location, "--version", version,
        *(["--dry-run"] if dry_run else []),
        *(["--config-dir", str(config_dir)] if config_dir else []),
    ]
    subprocess.run(cmd, cwd=ROOT)


def _scenario_files(location_dir: Path) -> list:
    return sorted(location_dir.glob("scenarios/scenario_*.json"))


def _run_generator_scoped(location: str, loc: Path, version: str, dry_run: bool,
                           config_dir: Path) -> list:
    """Run the generator against config_dir and return just the scenario files it
    wrote or rewrote. The generator names output scenarios from a config's
    internal content (location name, train counts, ...), not its filename --
    e.g. scenario_config_train_cleaning_late.json produces
    scenario_simple_service_location_4t_custom_train_cleaning_late.json -- so
    there is no way to predict the resulting name from config_dir's filenames.
    Comparing scenarios/ mtimes before and after is what actually identifies
    them, scoping the run to this subset instead of every scenario the
    location has ever accumulated.
    """
    before = {f: f.stat().st_mtime for f in _scenario_files(loc)}
    _run_generator(location, version, dry_run, config_dir)
    if dry_run:
        return []
    return [f for f in _scenario_files(loc) if f.stat().st_mtime != before.get(f)]


def _instance_stem(scenario: Path) -> str:
    return scenario.stem.removeprefix("scenario_")


def _write_progress(out_dir: Path, scenarios: list, tools: list, all_results: dict,
                     num_seeds=None) -> None:
    """Rewrite progress.csv from the current in-memory results -- called after
    every (instance, tool[, seed]) attempt finishes, so it always reflects
    exactly how far the run has gotten, including instances not yet started
    (blank cells) and tools outside --tools for this run (also blank, since
    they were never in scope here, not because they're pending). With
    --num-seeds, local_search shows "k/N" until all N seeds for that instance
    are done, then "done" -- planning never has seeds, so it's unaffected.
    """
    with open(out_dir / "progress.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["instance", "local_search", "planning"])
        writer.writeheader()
        for scenario in scenarios:
            instance = _instance_stem(scenario)
            done = all_results.get(instance, {})
            if num_seeds:
                n_done = sum(1 for s in range(1, num_seeds + 1) if f"solver_seed{s}" in done)
                local_search = "done" if n_done == num_seeds else (f"{n_done}/{num_seeds}" if n_done else "")
            else:
                local_search = "done" if "solver" in done else ""
            writer.writerow({
                "instance": instance,
                "local_search": local_search,
                "planning": "done" if "planner" in done else "",
            })


def _run_tool(tool: str, location: str, scenario: Path, out_dir: Path,
              version: str, force: bool, dry_run: bool, max_duration, seed) -> dict:
    result_path = out_dir / "result.json"
    if result_path.exists() and not force:
        print(f"  SKIP {tool} (result.json exists): {out_dir}")
        return json.loads(result_path.read_text())

    script = "run_solver.py" if tool == "solver" else "run_planner.py"
    cmd = [
        sys.executable, str(ROOT / script),
        "--location", location, "--scenario", scenario.name,
        "--output-dir", str(out_dir), "--version", version,
        *(["--dry-run"] if dry_run else []),
        *(["--max-duration", str(max_duration)] if max_duration is not None else []),
        # --seed is solver-only; run_planner.py has no seed concept at all.
        *(["--seed", str(seed)] if seed is not None and tool == "solver" else []),
    ]
    subprocess.run(cmd, cwd=ROOT)
    return json.loads(result_path.read_text()) if result_path.exists() else {
        "instance": _instance_stem(scenario), "tool": tool, "plan_produced": False,
    }


def _run_evaluator(location: str, scenario: Path, plan_path: Path, version: str,
                    force: bool, dry_run: bool) -> dict:
    eval_result_path = plan_path.parent / "eval_result.json"
    if eval_result_path.exists() and not force:
        print(f"  SKIP evaluator (eval_result.json exists): {plan_path.parent}")
        return json.loads(eval_result_path.read_text())

    cmd = [
        sys.executable, str(ROOT / "run_evaluator.py"),
        "--location", location, "--plan", str(plan_path),
        "--scenario", scenario.name, "--version", version,
        *(["--dry-run"] if dry_run else []),
    ]
    subprocess.run(cmd, cwd=ROOT)
    return json.loads(eval_result_path.read_text()) if eval_result_path.exists() else {
        "solved": False, "verdict": "error", "reason": "evaluator produced no result.json",
    }


def _run_and_record(tool: str, location: str, scenario: Path, tool_dir: Path, version: str,
                     force: bool, dry_run: bool, max_duration, seed, results: dict, key: str) -> None:
    run_result = _run_tool(tool, location, scenario, tool_dir, version, force, dry_run,
                            max_duration, seed)
    eval_result = None
    # A dry run never produces a real plan.json, so there is nothing for the
    # evaluator to dry-run against either — skip it rather than have it fail
    # a "no such plan file" check that would be misleading here.
    if not dry_run and run_result.get("plan_produced"):
        eval_result = _run_evaluator(location, scenario, tool_dir / "plan.json",
                                      version, force, dry_run)
    results[key] = {"run": run_result, "eval": eval_result}
    solved = bool(eval_result and eval_result.get("solved"))
    instance = scenario.stem.removeprefix("scenario_")
    print(f"  {instance} [{key}]  plan_produced={run_result.get('plan_produced')}  "
          f"solved={solved}")


def _run_instance(location: str, scenario: Path, tools: list, out_dir: Path,
                   version: str, force: bool, dry_run: bool, max_duration, seed, num_seeds,
                   all_results: dict, all_scenarios: list) -> None:
    instance = _instance_stem(scenario)
    results = all_results.setdefault(instance, {})
    for tool in tools:
        if tool == "solver" and num_seeds:
            for s in range(1, num_seeds + 1):
                tool_dir = out_dir / instance / FOLDER_NAMES[tool] / f"seed{s}"
                _run_and_record(tool, location, scenario, tool_dir, version, force, dry_run,
                                 max_duration, s, results, f"solver_seed{s}")
                if not dry_run:
                    _write_progress(out_dir, all_scenarios, tools, all_results, num_seeds)
        else:
            tool_dir = out_dir / instance / FOLDER_NAMES[tool]
            _run_and_record(tool, location, scenario, tool_dir, version, force, dry_run,
                             max_duration, seed, results, tool)
            if not dry_run:
                _write_progress(out_dir, all_scenarios, tools, all_results, num_seeds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run solver and/or planner (each followed by the evaluator) against "
                     "one or every scenario in a location, and record solved/not-solved.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--location", required=True, metavar="NAME")
    parser.add_argument("--scenario", metavar="NAME",
                        help="Run a single scenario instead of every scenario_*.json under "
                             "the location.")
    parser.add_argument("--tools", metavar="solver,planner", default="solver,planner",
                        help="Comma-separated subset of {solver,planner} to run (default: "
                             "both). planner is currently disabled, see below -- the default "
                             "will fail until it's fixed or you pass --tools solver.")
    parser.add_argument("--config-dir", metavar="DIR", type=Path,
                        help="Use scenario_config_*.json files from this directory instead of "
                             "<location>/configurations/. Restricts both generation and which "
                             "instances run afterward to this subset. Mutually exclusive with "
                             "--scenario.")
    parser.add_argument("--output-dir", required=True, metavar="DIR")
    parser.add_argument("--version", default="2.0.0")
    parser.add_argument("--max-duration", type=int, metavar="SECONDS",
                        help="Wall-clock budget passed through to each solver/planner run. "
                             "Both kill their container directly if exceeded; see "
                             "run_solver.py/run_planner.py --help.")
    parser.add_argument("--seed", type=int, metavar="N",
                        help="Passed through to run_solver.py's --seed (solver only -- "
                             "run_planner.py has no seed concept). Without this, every run "
                             "already uses the same implicit seed (1), so this is for "
                             "deliberately varying it. Mutually exclusive with --num-seeds.")
    parser.add_argument("--num-seeds", type=int, metavar="N",
                        help="Run the solver N times per instance with seeds 1..N, each into "
                             "its own <instance>/local_search/seed<i>/ -- the experimental-"
                             "setup doc's main-run protocol (\"the local-search solver five "
                             "times with recorded seeds\"). Solver only: --tools planner still "
                             "runs once regardless, since run_planner.py has no seed concept. "
                             "Mutually exclusive with --seed.")
    parser.add_argument("--certify-threshold", type=int, metavar="SECONDS",
                        help="Passed through to report_results.py's --certify-threshold. "
                             f"Default: {CERTIFY_MULTIPLIER} x --max-duration (a certification "
                             "pass conventionally runs at a multiple of the main budget, not "
                             "the same one); report_results.py's own default applies if "
                             "neither this nor --max-duration is given.")
    parser.add_argument("--force", dest="force", action="store_true", default=True,
                         help="Re-run even if a result.json/eval_result.json already exists "
                              "(default: on).")
    parser.add_argument("--skip-existing", dest="force", action="store_false",
                         help="Skip (instance, tool) pairs that already have a "
                              "result.json/eval_result.json, instead of re-running them.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them (evaluator steps "
                             "are skipped, since a dry run never produces a plan to evaluate).")
    args = parser.parse_args()

    loc = ROOT / args.location
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")

    if args.scenario and args.config_dir:
        sys.exit("--scenario and --config-dir are mutually exclusive.")
    if args.config_dir and not args.config_dir.is_dir():
        sys.exit(f"No such directory: {args.config_dir}")
    if args.seed is not None and args.num_seeds is not None:
        sys.exit("--seed and --num-seeds are mutually exclusive.")
    if args.num_seeds is not None and args.num_seeds < 1:
        sys.exit("--num-seeds must be at least 1.")

    tools = args.tools.split(",")
    for tool in tools:
        if tool not in ("solver", "planner"):
            sys.exit(f"Unknown tool {tool!r}; --tools takes a subset of solver,planner.")
    # planner is disabled for now: the planner image's plan-to-TORS converter
    # doesn't handle several action types the current image emits, so every
    # planner run fails before producing a plan (verified against
    # KleineBinckhorst scenarios) -- rather than let --tools silently burn
    # time on runs that can't succeed, refuse it outright. Re-enable by
    # deleting this check once planning-approach's converter is fixed; nothing
    # else in this file assumes planner is unavailable.
    if "planner" in tools:
        sys.exit("planner is currently disabled (known converter-gap bug in the planner "
                  "image -- every run fails before producing a plan). Use --tools solver.")
    if args.num_seeds is not None and "solver" not in tools:
        sys.exit("--num-seeds only applies to the solver; include it in --tools.")

    if args.config_dir:
        print(f"Generating scenarios for {loc.name} from {args.config_dir}...", flush=True)
        scenarios = _run_generator_scoped(args.location, loc, args.version, args.dry_run,
                                           args.config_dir)
        print()
        if not scenarios and not args.dry_run:
            sys.exit(f"Generator produced no scenario files from {args.config_dir} "
                      f"(check it and its configs are readable).")
    else:
        print(f"Generating scenarios for {loc.name}...", flush=True)
        _run_generator(args.location, args.version, args.dry_run)
        print()

        if args.scenario:
            scenarios = [loc / "scenarios" / args.scenario]
            if not scenarios[0].exists() and not args.dry_run:
                sys.exit(f"No such scenario: {scenarios[0]}")
        else:
            scenarios = _scenario_files(loc)
            if not scenarios and not args.dry_run:
                sys.exit(f"No scenario_*.json files found under {loc}/scenarios/ "
                          f"(and none in configurations/ either).")

    out_dir = Path(args.output_dir)
    print(f"Running {len(scenarios)} instance(s) x {tools} against {loc.name}...\n", flush=True)

    all_results = {}
    # if not args.dry_run:
    #     out_dir.mkdir(parents=True, exist_ok=True)
    #     _write_progress(out_dir, scenarios, tools, all_results, args.num_seeds)
    # for scenario in scenarios:
    #     _run_instance(args.location, scenario, tools, out_dir, args.version, args.force,
    #                   args.dry_run, args.max_duration, args.seed, args.num_seeds,
    #                   all_results, scenarios)

    print("\n--- Summary ---", flush=True)
    for instance, per_tool in all_results.items():
        line = "  ".join(
            f"{tool}={'solved' if (r['eval'] and r['eval'].get('solved')) else 'unsolved'}"
            for tool, r in per_tool.items()
        )
        print(f"  {instance}: {line}", flush=True)

    if not args.dry_run:
        print(flush=True)
        _run_report(out_dir, args.max_duration, args.certify_threshold)
        print(flush=True)
        _run_coverage_analysis(out_dir)


if __name__ == "__main__":
    main()
