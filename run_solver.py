#!/usr/bin/env python3
"""Run the HIP solver docker image on all scenario_*.json files, or on one
scenario in isolation via --scenario/--output-dir."""

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from docker_utils import ensure_docker_running, run_with_timeout, pull_flag

ROOT = Path(__file__).parent
DOCKER_IMAGE_VERSIONS = {
    "legacy": "ghcr.io/robust-rail-nl/hip:1.4.2",
    # Floats forward across ordinary releases rather than pinning one:
    # docker-push.sh only tags :latest on a real X.Y.Z build, so this needs no
    # update here when a new stable version ships. The --version key names a
    # pipeline configuration rather than a literal version number.
    "stable": "ghcr.io/robust-rail-nl/hip:latest",
    # Deliberately the plain image, not an -assert one. The solver is a
    # wall-clock-bounded local search, so an assertions-enabled build explores
    # less of the neighbourhood in the same budget and returns different plans
    # on any scenario that does not converge first — which would break the
    # comparison against the stable baseline. Run the -assert solver image
    # separately as a soak test (seed sweeps looking for a violation) instead.
    "stable-assert": "ghcr.io/robust-rail-nl/hip:latest",
    # Newest push to the edge branch: fixes worth running before they've gone
    # through PR review into main, not yet vetted enough to call stable.
    # Floating tag, always overwritten — see docker-push.sh in
    # robust-rail-solver.
    "edge": "ghcr.io/robust-rail-nl/hip:edge",
    "local": "hip:latest",
}
CONTAINER_DB = "/app/database"
TEMP_CONFIG = "config_solver_run.yaml"


def _parse_config(config_path: Path) -> dict:
    """Parse the solver YAML config without an external library."""
    config: dict = {}
    current_section: str | None = None
    with open(config_path) as f:
        for line in f:
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if line[0] in (" ", "\t"):
                if current_section is not None and ":" in line:
                    k, _, v = line.strip().partition(":")
                    v = v.strip().strip('"')
                    try:
                        v = int(v) if "." not in v else float(v)
                    except (ValueError, TypeError):
                        pass
                    config[current_section][k.strip()] = v
            else:
                current_section = None
                if ":" in line:
                    k, _, v = line.partition(":")
                    k = k.strip()
                    v = v.strip().strip('"')
                    if not v:
                        current_section = k
                        config[k] = {}
                    else:
                        try:
                            v = int(v) if "." not in v else float(v)
                        except (ValueError, TypeError):
                            pass
                        config[k] = v
    return config


def _fmt_section(d: dict, indent: int = 2) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}{k}: {v}" for k, v in d.items())


def _write_config(config_path: Path, scenario_name: str, plan_container_path: str, params: dict) -> None:
    tabu = params.get("TabuSearch", {
        "Iterations": 40, "IterationsUntilReset": 100, "TabuListLength": 16, "Bias": 0.5,
    })
    sa = params.get("SimulatedAnnealing", {
        "MaxDuration": 3600, "StopWhenFeasible": "true", "IterationsUntilReset": 15000,
        "T": 15, "A": 0.97, "Q": 2000, "Reset": 2000, "Bias": 0.2,
        "IntensifyOnImprovement": "false",
    })
    content = (
        f'LocationPath: "{CONTAINER_DB}/location.json"\n'
        f'ScenarioPath: "{CONTAINER_DB}/scenarios/{scenario_name}"\n'
        f'PlanPath: "{plan_container_path}"\n'
        f'Seed: {params.get("Seed", 1)}\n'
        f'DebugLevel: {params.get("DebugLevel", 0)}\n'
        f'\n'
        f'TabuSearch:\n{_fmt_section(tabu)}\n'
        f'\n'
        f'SimulatedAnnealing:\n{_fmt_section(sa)}\n'
    )
    config_path.write_text(content)


def _plan_name(scenario: Path) -> str:
    suffix = scenario.stem.removeprefix("scenario_")
    return f"plan_{suffix}.json"


def _run_scenario(docker_image: str, location_dir: Path, scenario: Path, dry_run: bool) -> bool:
    plan_name = _plan_name(scenario)
    config_path = location_dir / TEMP_CONFIG
    params = _parse_config(location_dir / "config_solver.yaml")

    cmd = [
        "docker", "run", "--rm",
        *pull_flag(docker_image),
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        f"--config={CONTAINER_DB}/{TEMP_CONFIG}",
    ]

    print(f"  {scenario.name}  ->  {plan_name}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

    plans_dir = location_dir / "plans"
    plans_dir.mkdir(exist_ok=True)
    plan_stem = Path(plan_name).stem
    out_file = plans_dir / f"{plan_stem}.out"
    err_file = plans_dir / f"{plan_stem}.err"

    _write_config(config_path, scenario.name, f"{CONTAINER_DB}/plans/{plan_name}", params)
    returncode = None
    ok = False
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr)
        returncode = result.returncode
        ok = returncode == 0
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)
    finally:
        config_path.unlink(missing_ok=True)

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
                          output_dir: Path, version: str, dry_run: bool,
                          max_duration=None, seed=None) -> dict:
    """Run one scenario, writing plan.json/solver.out/solver.err/result.json into
    output_dir instead of location_dir/plans/ — for experiment runs that need each
    (instance, tool) attempt kept in its own directory rather than the shared,
    filename-keyed plans/ folder every other scenario also writes into.
    """
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    # PID-suffixed so concurrent single-instance runs against the same location
    # never share this file — the batch loop above never runs scenarios in
    # parallel, so TEMP_CONFIG's fixed name was never a problem for it.
    config_path = location_dir / f"config_solver_run.{os.getpid()}.yaml"
    params = _parse_config(location_dir / "config_solver.yaml")
    if seed is not None:
        params["Seed"] = seed
    # What actually lands in the generated YAML's Seed: line -- _write_config
    # falls back to 1 when this key is absent, same as the location's own
    # config_solver.yaml already implicitly does today.
    seed_used = params.get("Seed", 1)
    container_name = f"solver-{uuid.uuid4().hex[:12]}"

    cmd = [
        "docker", "run", "--rm", "--name", container_name,
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        "--mount", f"type=bind,source={output_dir},target=/app/output",
        docker_image,
        f"--config={CONTAINER_DB}/{config_path.name}",
    ]

    plan_path = output_dir / "plan.json"
    print(f"  {scenario.name}  ->  {plan_path}")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return {}

    _write_config(config_path, scenario.name, "/app/output/plan.json", params)

    out_file = output_dir / "solver.out"
    err_file = output_dir / "solver.err"
    start = time.monotonic()
    start_iso = datetime.now(timezone.utc).isoformat()
    try:
        returncode, timed_out = run_with_timeout(cmd, out_file, err_file, container_name,
                                                  max_duration)
    finally:
        config_path.unlink(missing_ok=True)

    plan_produced = plan_path.exists() and plan_path.stat().st_size > 0
    record = {
        "instance": scenario.stem.removeprefix("scenario_"),
        "tool": "solver",
        "location": location_dir.name,
        "scenario": scenario.name,
        "version": version,
        "image": docker_image,
        "command": cmd,
        "max_duration": max_duration,
        "seed": seed_used,
        "start_time": start_iso,
        "end_time": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.monotonic() - start, 3),
        "exit_code": returncode,
        "timed_out": timed_out,
        "plan_produced": plan_produced,
    }
    (output_dir / "result.json").write_text(json.dumps(record, indent=2) + "\n")

    print(f"    exit {returncode}  timed_out={timed_out}  plan_produced={plan_produced}  "
          f"wall={record['wall_seconds']:.1f}s")
    if timed_out:
        print(f"    TIMEOUT (exceeded --max-duration {max_duration}s)", file=sys.stderr)
    elif returncode != 0:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the HIP solver on all scenario_*.json files."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory (e.g. Location_SimpleService).")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='stable',
                        help="Pick a docker image version ('legacy' no longer works against this "
                             "repo's fixtures — Phase 1 moved run_*.py to the unified format "
                             "unconditionally; 'local' is reserved for locally built images; "
                             "'edge' tracks the newest not-yet-vetted push to the edge branch).")
    parser.add_argument("--scenario", metavar="NAME",
                        help="Run a single scenario instead of every scenario_*.json under "
                             "the location (requires --location and --output-dir).")
    parser.add_argument("--output-dir", metavar="DIR", type=Path,
                        help="Write this single scenario's plan.json, solver.out/.err and "
                             "result.json here instead of <location>/plans/ (requires "
                             "--scenario).")
    parser.add_argument("--max-duration", type=int, metavar="SECONDS",
                        help="Wall-clock budget for this single scenario (requires "
                             "--scenario). Kills the container directly if exceeded, rather "
                             "than relying on the SimulatedAnnealing.MaxDuration config knob, "
                             "so a stuck run cannot outlive the budget regardless of what the "
                             "location's config_solver.yaml says.")
    parser.add_argument("--seed", type=int, metavar="N",
                        help="Override the solver's random seed for this run (requires "
                             "--scenario). The solver already seeds deterministically from "
                             "config_solver.yaml's Seed field -- this repo's own generated "
                             "runtime config defaults that to 1 when the location's file "
                             "doesn't set one, so runs are already reproducible without this "
                             "flag; it exists to vary the seed on purpose, e.g. running "
                             "several distinct seeds per instance.")
    args = parser.parse_args()

    if bool(args.scenario) != bool(args.output_dir):
        parser.error("--scenario and --output-dir must be given together.")
    if args.scenario and not args.location:
        parser.error("--scenario requires --location.")
    if args.max_duration and not args.scenario:
        parser.error("--max-duration requires --scenario.")
    if args.seed is not None and not args.scenario:
        parser.error("--seed requires --scenario.")

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
                                       args.output_dir, args.version, args.dry_run,
                                       args.max_duration, args.seed)
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
            if not _run_scenario(DOCKER_IMAGE_VERSIONS[args.version], loc, scenario, args.dry_run):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
