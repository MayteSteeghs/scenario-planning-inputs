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

result.json (written by run_solver.py/run_planner.py) records whether the
tool produced a plan; eval_result.json (written by run_evaluator.py, only
when a plan was produced) carries the "solved" verdict — solved is decided
by the evaluator alone, never by the solver/planner's own exit code.

Instance/config generation is out of scope here — this consumes whatever is
already in <location>/scenarios/scenario_*.json.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --tools/result.json still say "solver"/"planner" (they name the script/the
# tool field run_solver.py and run_planner.py themselves write), but the
# per-instance output directory is named after the search approach instead.
FOLDER_NAMES = {"solver": "local_search", "planner": "planning"}


def _scenario_files(location_dir: Path) -> list:
    return sorted(location_dir.glob("scenarios/scenario_*.json"))


def _instance_stem(scenario: Path) -> str:
    return scenario.stem.removeprefix("scenario_")


def _run_tool(tool: str, location: str, scenario: Path, out_dir: Path,
              version: str, force: bool, dry_run: bool, max_duration) -> dict:
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


def _run_instance(location: str, scenario: Path, tools: list, out_dir: Path,
                   version: str, force: bool, dry_run: bool, max_duration) -> dict:
    instance = _instance_stem(scenario)
    results = {}
    for tool in tools:
        tool_dir = out_dir / instance / FOLDER_NAMES[tool]
        run_result = _run_tool(tool, location, scenario, tool_dir, version, force, dry_run,
                                max_duration)
        eval_result = None
        # A dry run never produces a real plan.json, so there is nothing for the
        # evaluator to dry-run against either — skip it rather than have it fail
        # a "no such plan file" check that would be misleading here.
        if not dry_run and run_result.get("plan_produced"):
            eval_result = _run_evaluator(location, scenario, tool_dir / "plan.json",
                                          version, force, dry_run)
        results[tool] = {"run": run_result, "eval": eval_result}
        solved = bool(eval_result and eval_result.get("solved"))
        print(f"  {instance} [{tool}]  plan_produced={run_result.get('plan_produced')}  "
              f"solved={solved}")
    return results


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
                        help="Comma-separated subset of {solver,planner} to run "
                             "(default: both).")
    parser.add_argument("--output-dir", required=True, metavar="DIR")
    parser.add_argument("--version", default="2.0.0")
    parser.add_argument("--max-duration", type=int, metavar="SECONDS",
                        help="Wall-clock budget passed through to each solver/planner run. "
                             "Both kill their container directly if exceeded; see "
                             "run_solver.py/run_planner.py --help.")
    parser.add_argument("--force", action="store_true",
                         help="Re-run even if a result.json/eval_result.json already exists.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them (evaluator steps "
                             "are skipped, since a dry run never produces a plan to evaluate).")
    args = parser.parse_args()

    loc = ROOT / args.location
    if not loc.is_dir():
        sys.exit(f"No such location: {loc}")

    tools = args.tools.split(",")
    for tool in tools:
        if tool not in ("solver", "planner"):
            sys.exit(f"Unknown tool {tool!r}; --tools takes a subset of solver,planner.")

    if args.scenario:
        scenarios = [loc / "scenarios" / args.scenario]
        if not scenarios[0].exists():
            sys.exit(f"No such scenario: {scenarios[0]}")
    else:
        scenarios = _scenario_files(loc)
        if not scenarios:
            sys.exit(f"No scenario_*.json files found under {loc}/scenarios/")

    out_dir = Path(args.output_dir)
    print(f"Running {len(scenarios)} instance(s) x {tools} against {loc.name}...\n", flush=True)

    all_results = {}
    for scenario in scenarios:
        instance = _instance_stem(scenario)
        all_results[instance] = _run_instance(args.location, scenario, tools, out_dir,
                                               args.version, args.force, args.dry_run,
                                               args.max_duration)

    print("\n--- Summary ---")
    for instance, per_tool in all_results.items():
        line = "  ".join(
            f"{tool}={'solved' if (r['eval'] and r['eval'].get('solved')) else 'unsolved'}"
            for tool, r in per_tool.items()
        )
        print(f"  {instance}: {line}")


if __name__ == "__main__":
    main()
