#!/usr/bin/env python3
"""Run the full generator → solver → evaluator pipeline.

`planner` is available as an alternative to `solver`: both produce plans for the
evaluator to judge, by different means. See EXCLUSIVE_STEPS. --use-solver and
--use-planner are shorthand for the two three-step chains this produces most
often; --steps remains for anything else (a subset, a custom order).
"""

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ALL_STEPS = ["generator", "solver", "planner", "evaluator"]
DEFAULT_STEPS = ["generator", "solver", "evaluator"]
SCRIPTS = {
    "generator": ROOT / "run_generator.py",
    "solver": ROOT / "run_solver.py",
    "planner": ROOT / "run_planner.py",
    "evaluator": ROOT / "run_evaluator.py",
}

# run_solver.py and run_planner.py both write plans/plan_<suffix>.json. Running
# both over one location does not produce two sets of plans to compare, it
# produces one set from whichever ran last — and run_evaluator.py globs
# plans/plan_*.json, so nothing downstream can tell which tool made what.
# Rejected outright rather than documented: the failure is silent otherwise.
EXCLUSIVE_STEPS = {"solver", "planner"}


def _load_versions(step: str, version_key: str) -> str:
    script = SCRIPTS[step]
    spec = importlib.util.spec_from_file_location(f"_{step}", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DOCKER_IMAGE_VERSIONS.get(version_key, "?")


def _run_step(step: str, extra_args: list[str]) -> bool:
    script = SCRIPTS[step]
    cmd = [sys.executable, str(script)] + extra_args
    print(f"\n{'='*60}")
    print(f"  Step: {step}")
    print(f"{'='*60}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full generator → solver → evaluator pipeline."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Pass --dry-run to each step.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=['legacy', 'stable', 'stable-assert', 'edge', 'local'],
                        default='stable',
                        help="Pick a docker image version ('legacy' no longer works against this "
                             "repo's fixtures — Phase 1 moved run_*.py to the unified format "
                             "unconditionally; 'local' is reserved for locally built images; "
                             "'stable-assert' runs the evaluator with assertions enabled "
                             "for integration testing, and is not for baseline comparison; "
                             "'edge' runs the solver from its not-yet-vetted edge branch build "
                             "while generator and evaluator stay on stable).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--steps", metavar="STEPS", default=None,
                        help=f"Comma-separated list of steps to run (default: "
                             f"{','.join(DEFAULT_STEPS)}). Valid: {', '.join(ALL_STEPS)}. "
                             f"'planner' is an alternative to 'solver' and cannot be "
                             f"combined with it.")
    group.add_argument("--use-solver", action="store_true",
                        help=f"Shorthand for --steps {','.join(DEFAULT_STEPS)} (the default).")
    group.add_argument("--use-planner", action="store_true",
                        help="Shorthand for --steps generator,planner,evaluator.")
    args = parser.parse_args()

    if args.use_planner:
        steps_arg = "generator,planner,evaluator"
    elif args.use_solver or args.steps is None:
        steps_arg = ",".join(DEFAULT_STEPS)
    else:
        steps_arg = args.steps

    steps = [s.strip() for s in steps_arg.split(",")]
    unknown = [s for s in steps if s not in ALL_STEPS]
    if unknown:
        print(f"ERROR: unknown step(s): {', '.join(unknown)}. Valid: {', '.join(ALL_STEPS)}", file=sys.stderr)
        sys.exit(1)

    both = EXCLUSIVE_STEPS.intersection(steps)
    if len(both) > 1:
        print(f"ERROR: {' and '.join(sorted(both))} cannot run in one pipeline — they "
              f"both write plans/plan_<suffix>.json, so the second would overwrite the "
              f"first and the evaluator could not tell them apart. Run them separately, "
              f"keeping the plans/ output of each.", file=sys.stderr)
        sys.exit(1)

    extra: list[str] = []
    if args.dry_run:
        extra.append("--dry-run")
    extra += ["--version", args.version]
    if args.location:
        extra += ["--location", args.location]

    steps_str = " → ".join(steps)
    images = {step: _load_versions(step, args.version) for step in steps}
    version_summary = "  |  ".join(f"{step}: {images[step]}" for step in steps)

    print(f"\nPipeline starting: {steps_str}")
    print(f"  {version_summary}")

    for step in steps:
        if not _run_step(step, extra):
            print(f"\nPipeline aborted: step '{step}' failed.", file=sys.stderr)
            sys.exit(1)

    print(f"\nPipeline complete: {steps_str}")
    print(f"  {version_summary}")


if __name__ == "__main__":
    main()
