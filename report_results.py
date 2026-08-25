#!/usr/bin/env python3
"""Scan a run_experiment.py --output-dir results tree and compile two CSV reports.

Reads whatever result.json / eval_result.json / eval.out / eval.err files
run_experiment.py already wrote under <results-dir>/<instance>/{local_search,planning}/
-- this does not run anything itself.

local_search holds either one run directly (single --seed, or none) or one
subdirectory per seed (--num-seeds, seed1/, seed2/, ...) -- _tool_dirs below
detects which and yields one (label, dir) pair per actual run either way, so
everything downstream treats a 5-seed local_search the same as a solitary one.

  --runs-csv         One row per (instance, tool) attempt that was actually run
                      -- tool is "local_search_seed3" etc. when --num-seeds was
                      used, plain "local_search"/"planning" otherwise: the seed
                      actually used, plan_found (did the tool itself produce a
                      plan.json -- independent of what the evaluator later says
                      about it), timed_out, valid_plan (the evaluator's verdict
                      on that plan -- blank if no plan was ever produced to
                      evaluate), plan_length and move_actions (counted from
                      plan.json's own "actions" list -- total actions, and
                      how many have taskType.predefined == "Move"; blank if
                      no plan), and how many wall-clock seconds the run took.
                      plan_found and valid_plan are deliberately separate
                      facts: a tool can find a plan the evaluator then rejects,
                      and collapsing that into one column read as "no" for
                      both looks identical to the tool failing outright.
  --feasibility-csv  One row per instance: feasible (some tool's plan was
                      confirmed valid) / infeasible (the evaluator flagged the
                      scenario itself, not just one plan) / unresolved
                      (neither), and whether an unresolved instance has been
                      "tested" -- re-attempted at or above --certify-threshold
                      seconds, the closest thing to a certification pass this
                      pipeline has.

eval_result.json's own "verdict" field does not currently distinguish a
scenario-level rejection from an ordinary plan rejection (both come out as
"rejected"), so the infeasible check here re-reads eval.out/eval.err directly
for "Issue detected with the Scenario" -- the same string sweep_seeds.py's own
classifier keys on.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# Matches run_experiment.py's FOLDER_NAMES: the folder name is the search
# approach, not the script/--tools name.
TOOL_FOLDERS = ("local_search", "planning")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _tool_dirs(instance_dir: Path) -> list:
    """(label, dir) for every actual run under this instance: "local_search"/
    "planning" directly if that folder has a result.json of its own, or
    "local_search_seed<N>" per seed*/ subdirectory when --num-seeds was used
    (planning never has seeds -- run_planner.py has no seed concept).
    """
    pairs = []
    for folder in TOOL_FOLDERS:
        tool_dir = instance_dir / folder
        if (tool_dir / "result.json").exists():
            pairs.append((folder, tool_dir))
        elif tool_dir.is_dir():
            for seed_dir in sorted(tool_dir.glob("seed*")):
                if (seed_dir / "result.json").exists():
                    pairs.append((f"{folder}_{seed_dir.name}", seed_dir))
    return pairs


def _scenario_level_rejection(tool_dir: Path) -> bool:
    text = ""
    for name in ("eval.out", "eval.err"):
        f = tool_dir / name
        if f.exists():
            text += f.read_text(errors="replace")
    return "Issue detected with the Scenario" in text


def _plan_stats(tool_dir: Path) -> tuple:
    """(plan_length, move_actions) counted straight from plan.json's own
    "actions" list -- total actions, and how many have
    taskType.predefined == "Move". (None, None) if there's no plan to count.
    """
    plan = _read_json(tool_dir / "plan.json")
    actions = plan.get("actions")
    if actions is None:
        return None, None
    moves = sum(1 for a in actions if (a.get("taskType") or {}).get("predefined") == "Move")
    return len(actions), moves


def _tool_row(instance: str, tool: str, tool_dir: Path) -> dict:
    result = _read_json(tool_dir / "result.json")
    if not result:
        return None

    eval_result = _read_json(tool_dir / "eval_result.json")
    verdict = eval_result.get("verdict")
    plan_length, move_actions = _plan_stats(tool_dir)

    return {
        "instance": instance,
        "tool": tool,
        "seed": result.get("seed", ""),
        "plan_found": "yes" if result.get("plan_produced") else "no",
        "timed_out": "yes" if result.get("timed_out") else "no",
        "valid_plan": "yes" if verdict == "accepted" else ("no" if verdict else ""),
        "plan_length": plan_length if plan_length is not None else "",
        "move_actions": move_actions if move_actions is not None else "",
        "seconds": result.get("wall_seconds", ""),
    }


def _instance_feasibility(instance: str, instance_dir: Path, certify_threshold: int) -> dict:
    any_solved = False
    any_infeasible = False
    any_certified = False
    for _, tool_dir in _tool_dirs(instance_dir):
        result = _read_json(tool_dir / "result.json")
        eval_result = _read_json(tool_dir / "eval_result.json")
        if eval_result.get("solved"):
            any_solved = True
        if _scenario_level_rejection(tool_dir):
            any_infeasible = True
        if (result.get("max_duration") or 0) >= certify_threshold:
            any_certified = True

    if any_solved:
        classification = "feasible"
    elif any_infeasible:
        classification = "infeasible"
    else:
        classification = "unresolved"

    return {
        "instance": instance,
        "classification": classification,
        "tested": "yes" if (classification == "unresolved" and any_certified) else "",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compile CSV reports from a run_experiment.py results directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("results_dir", type=Path,
                        help="The --output-dir a run_experiment.py run wrote to.")
    parser.add_argument("--runs-csv", type=Path, default=Path("runs.csv"),
                        help="Path to write the per-(instance, tool) run report (default: runs.csv).")
    parser.add_argument("--feasibility-csv", type=Path, default=Path("feasibility.csv"),
                        help="Path to write the per-instance feasibility report "
                             "(default: feasibility.csv).")
    parser.add_argument("--certify-threshold", type=int, default=1800, metavar="SECONDS",
                        help="An unresolved instance is marked 'tested' if any of its recorded "
                             "runs used --max-duration at or above this (default: 1800).")
    args = parser.parse_args()

    if not args.results_dir.is_dir():
        sys.exit(f"No such directory: {args.results_dir}")

    instance_dirs = sorted(d for d in args.results_dir.iterdir() if d.is_dir())
    if not instance_dirs:
        sys.exit(f"No instance directories found under {args.results_dir}")

    run_rows = []
    feasibility_rows = []
    for instance_dir in instance_dirs:
        instance = instance_dir.name
        for tool_label, tool_dir in _tool_dirs(instance_dir):
            row = _tool_row(instance, tool_label, tool_dir)
            if row:
                run_rows.append(row)
        feasibility_rows.append(
            _instance_feasibility(instance, instance_dir, args.certify_threshold)
        )

    with open(args.runs_csv, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "instance", "tool", "seed", "plan_found", "timed_out", "valid_plan",
                "plan_length", "move_actions", "seconds",
            ],
        )
        writer.writeheader()
        writer.writerows(run_rows)

    with open(args.feasibility_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["instance", "classification", "tested"])
        writer.writeheader()
        writer.writerows(feasibility_rows)

    print(f"Wrote {len(run_rows)} run(s) to {args.runs_csv}")
    print(f"Wrote {len(feasibility_rows)} instance(s) to {args.feasibility_csv}")


if __name__ == "__main__":
    main()
