#!/usr/bin/env python3
"""Run the TORS evaluator docker image on all plan files that have a matching
scenario, or on one plan in isolation via --plan/--scenario."""

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
DOCKER_IMAGE_VERSIONS = {
    "legacy": "ghcr.io/robust-rail-nl/tors:1.3.1",
    "2.0.0": "ghcr.io/robust-rail-nl/tors:2.0.0",
    # The evaluator is the oracle the pipeline trusts, and its assertions build
    # produces the same verdicts and .err content as the plain one (verified
    # across all KleineBinckhorst scenarios — .txt trace files can differ in
    # line order between separately-built binaries, see docs/roadmap-2.0.0.md,
    # but never in content) while turning an internal invariant violation into
    # an abort rather than a verdict computed from corrupt state. A run that
    # trips one exits 134/139 with the assertion text in the .err file, which
    # reads very differently from an ordinary "plan is not valid".
    "2.0.0-assert": "ghcr.io/robust-rail-nl/tors:2.0.0-assert",
    "local": "tors:latest",
}
CONTAINER_DB = "/app/database"


def _scenario_name(plan: Path) -> str:
    return plan.stem.removeprefix("plan_")


def _run_plan(docker_image: str, location_dir: Path, plan: Path, dry_run: bool) -> bool:
    name = _scenario_name(plan)
    scenario = location_dir / "scenarios" / f"scenario_{name}.json"

    if not scenario.exists():
        print(f"  SKIP {plan.name}: no matching scenario_{name}.json", file=sys.stderr)
        return True  # not a failure — plan may predate the scenario file

    # The evaluator needs this alongside location.json, not just
    # location.json + scenario — without it the container fails deep inside
    # TORS with a misleading "specified file '/app/database' does not
    # exist" (it means config.json, not the mount itself).
    if not (location_dir / "config.json").exists():
        print(f"  SKIP {plan.name}: {location_dir}/config.json missing — "
              f"required by the evaluator alongside location.json", file=sys.stderr)
        return False

    eval_dir = location_dir / "evaluations"
    eval_dir.mkdir(exist_ok=True)
    out_file = eval_dir / f"eval_{name}.out"
    err_file = eval_dir / f"eval_{name}.err"

    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        docker_image,
        "--mode", "EVAL_AND_STORE",
        "--path_location", CONTAINER_DB,
        "--path_scenario", f"{CONTAINER_DB}/scenarios/scenario_{name}.json",
        "--path_plan", f"{CONTAINER_DB}/plans/{plan.name}",
        "--path_eval_result", f"{CONTAINER_DB}/evaluations/eval_{name}.txt",
        "--plan_type", "Solver",
    ]

    print(f"  {plan.name}  ->  evaluations/eval_{name}.txt")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return True

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


def _classify_verdict(out_text: str, err_text: str, txt_text: str) -> tuple[str, str]:
    """Read the evaluator's own verdict out of its output, the same string checks
    sweep_seeds.py's _classify uses (EVAL_AND_STORE writes the rejection reason to
    the result file, not stdout, so txt_text matters too).
    """
    for line in (err_text + out_text).splitlines():
        if "Issue detected with the Scenario" in line:
            return "rejected", line.split("Scenario:", 1)[-1].strip()
    if "The plan is valid" in out_text:
        return "accepted", ""
    reason = next(
        (
            ln.split("The action is invalid.", 1)[-1].strip().rstrip(".")
            for ln in (out_text + txt_text).splitlines()
            if "Scenario failed" in ln
        ),
        None,
    )
    if reason is not None:
        return "rejected", reason
    if txt_text.strip():
        return "rejected", "plan rejected"
    return "error", "evaluator produced no readable verdict"


def _run_plan_single(docker_image: str, location_dir: Path, plan: Path, scenario: Path,
                      version: str, dry_run: bool) -> dict:
    """Evaluate a single plan file wherever it lives (e.g. a run_solver.py/
    run_planner.py --output-dir), writing eval.out/eval.err/eval_result.json beside
    it rather than into location_dir/evaluations/ — so a solver run's and a
    planner run's evaluator verdicts stay next to that run's own plan and result.json.
    """
    plan = plan.resolve()
    plan_dir = plan.parent

    cmd = [
        "docker", "run", "--rm",
        *(["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform != "win32" else []),
        "--mount", f"type=bind,source={location_dir.resolve()},target={CONTAINER_DB}",
        "--mount", f"type=bind,source={plan_dir},target=/app/planio",
        docker_image,
        "--mode", "EVAL_AND_STORE",
        "--path_location", CONTAINER_DB,
        "--path_scenario", f"{CONTAINER_DB}/scenarios/{scenario.name}",
        "--path_plan", f"/app/planio/{plan.name}",
        "--path_eval_result", "/app/planio/eval.txt",
        "--plan_type", "Solver",
    ]

    print(f"  {plan}  ->  {plan_dir}/eval_result.json")
    if dry_run:
        print(f"    [dry-run] {' '.join(cmd)}")
        return {}

    out_file = plan_dir / "eval.out"
    err_file = plan_dir / "eval.err"
    txt_file = plan_dir / "eval.txt"
    start = time.monotonic()
    start_iso = datetime.now(timezone.utc).isoformat()
    returncode = None
    try:
        with open(out_file, "w") as fout, open(err_file, "w") as ferr:
            result = subprocess.run(cmd, stdout=fout, stderr=ferr)
        returncode = result.returncode
    except Exception as exc:
        print(f"    ERROR: {exc}", file=sys.stderr)

    out_text = out_file.read_text(errors="replace") if out_file.exists() else ""
    err_text = err_file.read_text(errors="replace") if err_file.exists() else ""
    txt_text = txt_file.read_text(errors="replace") if txt_file.exists() else ""
    verdict, reason = _classify_verdict(out_text, err_text, txt_text)

    record = {
        "instance": scenario.stem.removeprefix("scenario_"),
        "location": location_dir.name,
        "scenario": scenario.name,
        "plan": str(plan),
        "version": version,
        "image": docker_image,
        "command": cmd,
        "start_time": start_iso,
        "end_time": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": round(time.monotonic() - start, 3),
        "exit_code": returncode,
        "verdict": verdict,
        "solved": verdict == "accepted",
        "reason": reason,
    }
    (plan_dir / "eval_result.json").write_text(json.dumps(record, indent=2) + "\n")

    print(f"    exit {returncode}  verdict={verdict}  solved={record['solved']}  "
          f"wall={record['wall_seconds']:.1f}s")
    if returncode != 0:
        print(f"    FAILED (exit {returncode})", file=sys.stderr)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TORS evaluator on all plans that have a matching scenario."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print docker commands without executing them.")
    parser.add_argument("--location", metavar="NAME",
                        help="Restrict to a single Location_* directory.")
    parser.add_argument("--version", choices=DOCKER_IMAGE_VERSIONS.keys(), default='2.0.0',
                        help="Pick a docker image version ('legacy' no longer works against this "
                             "repo's fixtures — Phase 1 moved run_*.py to the unified format "
                             "unconditionally; 'local' is reserved for locally built images).")
    parser.add_argument("--plan", metavar="PATH", type=Path,
                        help="Evaluate a single plan file instead of every plans/plan_*.json "
                             "under the location (requires --location and --scenario). "
                             "eval.out/.err and eval_result.json are written beside the plan.")
    parser.add_argument("--scenario", metavar="NAME",
                        help="Scenario filename matching --plan (required with --plan).")
    args = parser.parse_args()

    if bool(args.plan) != bool(args.scenario):
        parser.error("--plan and --scenario must be given together.")
    if args.plan and not args.location:
        parser.error("--plan requires --location.")

    if not args.dry_run:
        ensure_docker_running()

    if args.plan:
        loc = ROOT / args.location
        if not loc.is_dir():
            sys.exit(f"No such location: {loc}")
        if not args.plan.exists():
            sys.exit(f"No such plan file: {args.plan}")
        scenario = loc / "scenarios" / args.scenario
        if not scenario.exists():
            sys.exit(f"No such scenario: {scenario}")
        if not (loc / "config.json").exists():
            sys.exit(f"{loc}/config.json missing — required by the evaluator alongside location.json")
        record = _run_plan_single(DOCKER_IMAGE_VERSIONS[args.version], loc, args.plan, scenario,
                                   args.version, args.dry_run)
        if not args.dry_run and record.get("exit_code") != 0:
            sys.exit(1)
        return

    locations = [ROOT / args.location] if args.location else sorted(ROOT.glob("Location_*/"))

    total, errors = 0, 0
    for loc in locations:
        if not loc.is_dir():
            print(f"WARNING: {loc} not found, skipping.", file=sys.stderr)
            continue
        plans = sorted(loc.glob("plans/plan_*.json"))
        if not plans:
            continue
        print(f"\n{loc.name} ({len(plans)} plan(s))")
        for plan in plans:
            total += 1
            if not _run_plan(DOCKER_IMAGE_VERSIONS[args.version], loc, plan, args.dry_run):
                errors += 1

    print(f"\nDone: {total - errors}/{total} succeeded.")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
