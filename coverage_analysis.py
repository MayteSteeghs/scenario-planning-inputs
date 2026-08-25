#!/usr/bin/env python3
"""RQ1 (Coverage) statistics from a run_experiment.py results directory, per
the experimental-setup doc's Section 4.1 protocol:

  - Coverage (fraction of instances solved) for local_search and planning,
    each with a 95% Wilson score interval, on two subsets:
      * the full instance set (secondary; denominator stated)
      * the known-feasible subset (primary) -- instances where either tool's
        plan was evaluator-confirmed, i.e. report_results.py's "feasible"
        classification. This does not require a separate certification pass:
        any recorded solve, at any budget, is enough to call an instance
        known-feasible, matching the doc's "any instance solved at the
        extended budget is marked known feasible."
  - An exact McNemar test (two-sided exact binomial test on the discordant
    pairs) on the paired per-instance solved/not-solved outcomes, on both
    subsets. Flagged as underpowered/descriptive-only below 10 discordant
    pairs, per the doc's own caveat about McNemar's power.

Out of scope here, deliberately: RQ2 (scaling) is marked TODO in the doc
itself; RQ3 (runtime) asks for a cactus plot, not a hypothesis test; the
soundness check (4.4) needs a pre-labeled ground-truth infeasible fixture
set to check accepted plans against, which nothing in this pipeline
currently tracks -- report_results.py's "infeasible" classification is
empirically discovered by the evaluator during this run, not a fixture
list, so treating it as ground truth here would be wrong.

Reads the same result.json/eval_result.json files report_results.py does
(and reuses its instance-scanning helpers); does not run anything itself.
"""

import argparse
import sys
from math import comb
from pathlib import Path

import report_results as rr

Z_95 = 1.96


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


def mcnemar_exact_p(n_a_only: int, n_b_only: int) -> float:
    """Exact two-sided McNemar test: a binomial test on the discordant pairs
    against p=0.5, doubling the smaller tail (the standard exact-McNemar
    construction; equivalent to scipy.stats.binomtest(k, n, 0.5) on
    k=min(n_a_only, n_b_only), n=n_a_only+n_b_only).
    """
    n = n_a_only + n_b_only
    if n == 0:
        return 1.0
    k = min(n_a_only, n_b_only)
    tail = sum(comb(n, x) * 0.5 ** n for x in range(0, k + 1))
    return min(1.0, 2 * tail)


def _tool_solved(instance_dir: Path, folder: str) -> bool:
    """True if ANY run under this tool's folder was evaluator-confirmed
    solved -- a single run (no --num-seeds), or any one of several seed*/
    subdirectories (--num-seeds): the doc's coverage definition is per
    instance per solver, and a solver that finds a plan on any one of its
    seeds has covered that instance.
    """
    direct = rr._read_json(instance_dir / folder / "eval_result.json")
    if direct:
        return bool(direct.get("solved"))
    return any(
        rr._read_json(seed_dir / "eval_result.json").get("solved")
        for seed_dir in sorted((instance_dir / folder).glob("seed*"))
    )


def _format_subset(label: str, solver: list, planner: list) -> str:
    n = len(solver)
    if n == 0:
        return f"--- {label} (n=0) ---\n  no instances in this subset."

    solver_hits = sum(solver)
    planner_hits = sum(planner)
    p_solver, solver_lo, solver_hi = wilson_interval(solver_hits, n)
    p_planner, planner_lo, planner_hi = wilson_interval(planner_hits, n)

    n_both = sum(a and b for a, b in zip(solver, planner))
    n_solver_only = sum(a and not b for a, b in zip(solver, planner))
    n_planner_only = sum(b and not a for a, b in zip(solver, planner))
    n_neither = n - n_both - n_solver_only - n_planner_only
    discordant = n_solver_only + n_planner_only
    p_value = mcnemar_exact_p(n_solver_only, n_planner_only)

    lines = [
        f"--- {label} (n={n}) ---",
        f"  local_search coverage: {solver_hits}/{n} = {p_solver:.3f}  "
        f"95% CI [{solver_lo:.3f}, {solver_hi:.3f}]",
        f"  planning     coverage: {planner_hits}/{n} = {p_planner:.3f}  "
        f"95% CI [{planner_lo:.3f}, {planner_hi:.3f}]",
        f"  paired: both={n_both}  local_search only={n_solver_only}  "
        f"planning only={n_planner_only}  neither={n_neither}",
        f"  McNemar exact test (discordant pairs={discordant}): p={p_value:.4f}"
        if discordant > 0 else
        "  McNemar exact test: no discordant pairs -- untestable (solvers agree on everything).",
    ]
    if 0 < discordant < 10:
        lines.append("  NOTE: fewer than 10 discordant pairs -- underpowered regardless of "
                      "instance count; treat this as descriptive, not a significance claim "
                      "(per the experimental-setup doc's RQ1 caveat).")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RQ1 coverage statistics (Wilson intervals + exact McNemar) from a "
                     "run_experiment.py results directory.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("results_dir", type=Path,
                        help="The --output-dir a run_experiment.py run wrote to.")
    parser.add_argument("--output", type=Path, metavar="FILE",
                        help="Also write the report to this file (always printed to stdout).")
    args = parser.parse_args()

    if not args.results_dir.is_dir():
        sys.exit(f"No such directory: {args.results_dir}")

    instance_dirs = sorted(d for d in args.results_dir.iterdir() if d.is_dir())
    if not instance_dirs:
        sys.exit(f"No instance directories found under {args.results_dir}")

    solver_all, planner_all = [], []
    solver_feasible, planner_feasible = [], []
    for instance_dir in instance_dirs:
        solved_solver = _tool_solved(instance_dir, "local_search")
        solved_planner = _tool_solved(instance_dir, "planning")
        solver_all.append(solved_solver)
        planner_all.append(solved_planner)
        # certify_threshold doesn't affect classification, only the "tested"
        # flag this script doesn't use -- any value is fine here.
        classification = rr._instance_feasibility(
            instance_dir.name, instance_dir, certify_threshold=0
        )["classification"]
        if classification == "feasible":
            solver_feasible.append(solved_solver)
            planner_feasible.append(solved_planner)

    report = [
        "RQ1: Coverage (local_search vs. planning)",
        "",
        _format_subset("Known-feasible subset (primary)", solver_feasible, planner_feasible),
        "",
        _format_subset(f"Full instance set (secondary, denominator={len(instance_dirs)})",
                        solver_all, planner_all),
    ]
    text = "\n".join(report)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
