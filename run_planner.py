#!/usr/bin/env python3
"""Run the planner docker image on all scenario_*.json files, or on one
scenario in isolation via --scenario/--output-dir.

An alternative to the HIP solver step, not an addition: it converts each
scenario to PDDL, plans, and converts the result back to TORS JSON at
plans/plan_<suffix>.json — the same output convention run_evaluator.py
consumes, and the same filename run_solver.py writes. Running both against one
location would have them overwrite each other, so run_pipeline.py refuses the
combination.

The image is built and published from ../planning-approach by its
docker-push.sh.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from docker_utils import ensure_docker_running

ROOT = Path(__file__).parent
CONTAINER_DB = "/app/database"

# Named DOCKER_IMAGE_VERSIONS like every other step's, because run_pipeline.py
# reads that attribute by name to report which images a run will use. It was
# PLANNER_DOCKER_IMAGE_VERSIONS, which made `--steps planner` an AttributeError.
#
# The keys mirror the other steps' --version choices so the pipeline can pass
# --version uniformly, but they do not all mean something here:
#
# - "legacy" has no honest value. The planner step did not exist in 1.x, so
#   there is no 1.x planner image to compare against. It maps to the current
#   one rather than to a tag that was never built.
# - "2.0.0-assert" likewise: the assertions builds are the evaluator's and the
#   solver's. This image has no such variant, so the selector resolves to the
#   plain image and the run stays comparable.
#
# The version is planning-approach's own (see its VERSION file), deliberately
# not 2.0.0 — that number belongs to the repos sharing an interchange format.
# 0.2.1 is the first image that plans every location. Neither predecessor is
# worth pinning back to for a comparison run:
#
#   0.1.0  matched no pattern for the corridor model's compiled departure, so it
#          dropped every plan's Exit and the moves leading to it, and reported
#          success. Its plans stop at the last service task and are not solutions.
#   0.2.0  emits whole plans but raises UnboundLocalError on any plan whose
#          departing train never moved — fine on SimpleService, dead on
#          KleineBinckhorst.
DOCKER_IMAGE_VERSIONS = {
    "legacy": "ghcr.io/robust-rail-nl/planner:0.3.0",
    "2.0.0": "ghcr.io/robust-rail-nl/planner:0.3.0",
    "2.0.0-assert": "ghcr.io/robust-rail-nl/planner:0.3.0",
    "local": "planner:latest",
}


def _scenario_name(scenario: Path) -> str:
    return scenario.stem.removeprefix("scenario_")


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, planner: str, dry_run: bool) -> bool:
    name = _scenario_name(scenario)
    plan_name = f"plan_{name}.json"

    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        "--location", f"{CONTAINER_DB}/location.json",
        "--scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--planner", planner,
        "--output", f"{CONTAINER_DB}/plans/{plan_name}",
    ]

    print(f"  {scenario.name}  ->  {plan_name}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    out_file = plans_dir / f"plan_{name}.out"
    err_file = plans_dir / f"plan_{name}.err"

    returncode = None
    ok = False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr)
        returncode = result.returncode
        ok = returncode == 0
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)

    with open(err_file, "a") as f:
        f.write(f"--- exit: {returncode if returncode is not None else 'error'}\n")
    out_lines = len(out_file.read_text().splitlines()) if out_file.exists() else 0
    err_lines = len(err_file.read_text().splitlines()) if err_file.exists() else 0
    if ok and err_lines <= 1:
        err_file.unlink(missing_ok=True)
        err_lines = 0
    err_part = f"  stderr: {err_lines}L" if err_lines else ""
    print(f"    stdout: {out_lines}L{err_part}  (exit {returncode})")

    if not ok and returncode is not None:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return ok


def _run_scenario_single(docker_image: str, location_dir: Path, scenario: Path,
                          planner: str, output_dir: Path, version: str, dry_run: bool) -> dict:
    """Run one scenario, writing plan.json/planner.out/planner.err/result.json into
    output_dir instead of location_dir/plans/ — mirrors run_solver.py's
    --scenario/--output-dir mode so the two tools' single-instance output is laid
    out the same way for a solver-vs-planner comparison.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        "--mount", f"type=bind,source={output_dir},target=/app/output",
        docker_image,
        "--location", f"{CONTAINER_DB}/location.json",
        "--scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--planner", planner,
        "--output", "/app/output/plan.json",
    ]

    plan_path = output_dir / "plan.json"
    print(f"  {scenario.name}  ->  {plan_path}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return {}

    out_file = output_dir / "planner.out"
    err_file = output_dir / "planner.err"
    start = time.monotonic()
    start_iso = datetime.now(timezone.utc).isoformat()
    returncode = None
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr)
        returncode = result.returncode
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)

    plan_produced = plan_path.exists() and plan_path.stat().st_size > 0
    record = {
        "instance": scenario.stem.removeprefix("scenario_"),
        "tool": "planner",
        "planner_impl": planner,
        "location": location_dir.name,
        "scenario": scenario.name,
        "version": version,
        "image": docker_image,
        "command": cmd,
        "start_time": start_iso,
        "end_time": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.monotonic() - start, 3),
        "exit_code": returncode,
        "plan_produced": plan_produced,
    }
    (output_dir / "result.json").write_text(json.dumps(record, indent=2) + "\n")

    print(f"    exit {returncode}  plan_produced={plan_produced}  "
          f"wall={record['wall_seconds']:.1f}s")
    if returncode != 0:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the planner on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default="local",
                        help="Pick a docker image version.")
    parser.add_argument("--planner", choices=["symbolic", "enhsp"], default="enhsp",
                        help="Planner implementation to use inside the container.")
    parser.add_argument("--scenario", metavar="NAME",
                        help="Run a single scenario instead of every scenario_*.json under "
                             "the location (requires --location and --output-dir).")
    parser.add_argument("--output-dir", metavar="DIR", type=Path,
                        help="Write this single scenario's plan.json, planner.out/.err and "
                             "result.json here instead of <location>/plans/ (requires "
                             "--scenario).")
    args = parser.parse_args()

    if bool(args.scenario) != bool(args.output_dir):
        parser.error("--scenario and --output-dir must be given together.")
    if args.scenario and not args.location:
        parser.error("--scenario requires --location.")

    if not args.dry_run:
        ensure_docker_running()

    if args.scenario:
        loc = ROOT / args.location
        if not loc.is_dir():
            sys.exit(f"No such location: {loc}")
        scenario = loc / "scenarios" / args.scenario
        if not scenario.exists():
            sys.exit(f"No such scenario: {scenario}")
        record = _run_scenario_single(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario,
                                       args.planner, args.output_dir, args.version, args.dry_run)
        if not args.dry_run and record.get("exit_code") != 0:
            sys.exit(1)
        return

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        scenarios = sorted(loc.glob("scenarios/scenario_*.json"))
        if not scenarios:
            continue
        print(f"\n{loc.name} ({len(scenarios)} scenario(s))")
        for scenario in scenarios:
            total += 1
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.planner, args.dry_run):
                errors += 1

    if total == 0:
        # This script spent the whole scenario-unification period globbing
        # scenario_solver_*.json, a filename that stopped existing, and reported
        # "Done: 0/0 succeeded" with exit 0 every time — indistinguishable from
        # a clean run. Finding no work is nearly always a broken glob or a wrong
        # --location rather than a real empty repo, so say so out loud.
        print("WARNING: no scenarios/scenario_*.json found — nothing was planned.",
              file=sys.stderr)

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
