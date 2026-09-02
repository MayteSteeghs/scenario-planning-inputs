#!/usr/bin/env python3
"""Generate a sweep of scenario_config_*.json files for KleineBinckhorst.

Iterates over every combination of (number of trains) x (instances) x
(matching strategy) and writes one config per combination into
configurations/, or configurations/<--subfolder>/ if given. Use
run_generator.py to actually run the generator on them, or point
run_experiment.py's --config-dir at the subfolder to scope a whole
generate+solve+plan+evaluate run to just this sweep.
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent
CONFIG_DIR = ROOT / "configurations"

MATCHING_NAME_TO_ID = {"FIFO": 0, "random": 1, "LIFO": 2}

DEFAULT_NUMBER_OF_TRAINS = [5, 10, 15, 20, 25, 30]
DEFAULT_NUMBER_OF_INSTANCES = 10
DEFAULT_MATCHINGS = ["FIFO", "random", "LIFO"]
DEFAULT_SEED = 42
DEFAULT_TIME_WINDOW_PER_TRAIN = 300
DEFAULT_MIN_GAP_ON_GATEWAY = 180
DEFAULT_TRAIN_UNIT_TYPES = ["VIRM-4", "VIRM-6", "ICM-3", "ICM-4", "SNG-3", "SNG-4", "SLT-4", "SLT-6", "DDZ-4", "DDZ-6"]
DEFAULT_SUPER_TYPE_RATIO = 0.5
DEFAULT_UNITS_PER_COMPOSITION = [1, 2, 3]
DEFAULT_MATCHING_COMPLEXITY = 0.3
DEFAULT_INSTANDING_RATIO = 0.3
DEFAULT_OUTSTANDING_RATIO = 0.1

# Maps JSON keys / CLI dest names to their built-in default.
DEFAULTS = {
    "number_of_trains": DEFAULT_NUMBER_OF_TRAINS,
    "number_of_instances": DEFAULT_NUMBER_OF_INSTANCES,
    "matchings": DEFAULT_MATCHINGS,
    "seed": DEFAULT_SEED,
    "time_window_per_train": DEFAULT_TIME_WINDOW_PER_TRAIN,
    "mixed_traffic": False,
    "min_gap_on_gateway": DEFAULT_MIN_GAP_ON_GATEWAY,
    "perform_servicing": False,
    "train_unit_types": DEFAULT_TRAIN_UNIT_TYPES,
    "super_type_ratio": DEFAULT_SUPER_TYPE_RATIO,
    "units_per_composition": DEFAULT_UNITS_PER_COMPOSITION,
    "matching_complexity": DEFAULT_MATCHING_COMPLEXITY,
    "instanding_ratio": DEFAULT_INSTANDING_RATIO,
    "outstanding_ratio": DEFAULT_OUTSTANDING_RATIO,
}


def main() -> None:
    # First pass: only look for --from-json, so its values can seed the
    # defaults of every other flag before those flags are defined below.
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--from-json", "-j", type=Path)
    pre_args, _ = pre_parser.parse_known_args()

    file_values = {}
    if pre_args.from_json:
        with open(pre_args.from_json) as f:
            file_values = json.load(f)
        unknown_keys = file_values.keys() - DEFAULTS.keys()
        if unknown_keys:
            raise ValueError(f"Unknown key(s) in {pre_args.from_json}: {sorted(unknown_keys)}")

    def default(key):
        return file_values.get(key, DEFAULTS[key])

    parser = argparse.ArgumentParser(
        parents=[pre_parser],
        description="Generate a sweep of scenario_config_*.json files over trains x instances x matchings.",
    )
    parser.add_argument("--number-of-trains", "-n", nargs="+", type=int, default=default("number_of_trains"),
                        help=f"List of train counts to sweep over, e.g. -n 5 10 15 20 (default: {DEFAULT_NUMBER_OF_TRAINS}).")
    parser.add_argument("--number-of-instances", "-i", type=int, default=default("number_of_instances"),
                        help=f"How many instances to generate per (trains, matching) combo (default: {DEFAULT_NUMBER_OF_INSTANCES}).")
    parser.add_argument("--matchings", "-m", nargs="+", choices=MATCHING_NAME_TO_ID.keys(), default=default("matchings"),
                        help=f"List of matching strategies to sweep over, e.g. -m FIFO random (default: {DEFAULT_MATCHINGS}).")
    parser.add_argument("--seed", "-s", type=int, default=default("seed"),
                        help=f"Base seed; trains index j and instance index i give seed * (j + i + 1) "
                             f"(default: {DEFAULT_SEED}).")
    parser.add_argument("--time-window-per-train", "-t", type=int, default=default("time_window_per_train"),
                        help=f"Time window per train, used to derive end_time (default: {DEFAULT_TIME_WINDOW_PER_TRAIN}).")
    parser.add_argument("--mixed-traffic", action="store_true", default=default("mixed_traffic"),
                        help="Enable mixed traffic (default: False).")
    parser.add_argument("--min-gap-on-gateway", type=int, default=default("min_gap_on_gateway"),
                        help=f"Minimum gap on gateway in seconds (default: {DEFAULT_MIN_GAP_ON_GATEWAY}).")
    parser.add_argument("--perform-servicing", action="store_true", default=default("perform_servicing"),
                        help="Enable servicing (default: False).")
    parser.add_argument("--train-unit-types", nargs="+", default=default("train_unit_types"),
                        help=f"Train unit types (default: {DEFAULT_TRAIN_UNIT_TYPES}).")
    parser.add_argument("--super-type-ratio", type=float, default=default("super_type_ratio"),
                        help=f"Super type ratio (default: {DEFAULT_SUPER_TYPE_RATIO}).")
    parser.add_argument("--units-per-composition", nargs="+", type=int, default=default("units_per_composition"),
                        help=f"Units per composition (default: {DEFAULT_UNITS_PER_COMPOSITION}).")
    parser.add_argument("--matching-complexity", type=float, default=default("matching_complexity"),
                        help=f"Matching complexity (default: {DEFAULT_MATCHING_COMPLEXITY}).")
    parser.add_argument("--instanding-ratio", type=float, default=default("instanding_ratio"),
                        help=f"Instanding ratio (default: {DEFAULT_INSTANDING_RATIO}).")
    parser.add_argument("--outstanding-ratio", type=float, default=default("outstanding_ratio"),
                        help=f"Outstanding ratio (default: {DEFAULT_OUTSTANDING_RATIO}).")
    parser.add_argument("--subfolder", metavar="NAME",
                        help="Write configs into configurations/<NAME>/ instead of directly "
                             "into configurations/ -- keeps one sweep's configs separate from "
                             "another's (or from the curated example configs already there), "
                             "and gives run_experiment.py's --config-dir a self-contained "
                             "directory to point at: --config-dir configurations/<NAME>.")
    args = parser.parse_args()

    invalid_matchings = set(args.matchings) - MATCHING_NAME_TO_ID.keys()
    if invalid_matchings:
        parser.error(f"invalid matching(s): {sorted(invalid_matchings)}")

    total_runs = len(args.number_of_trains) * args.number_of_instances * len(args.matchings)
    print(
        f"This will generate {total_runs} config(s): "
        f"{len(args.number_of_trains)} train count(s) x "
        f"{args.number_of_instances} instance(s) x "
        f"{len(args.matchings)} matching(s)."
    )

    config_dir = (CONFIG_DIR / args.subfolder) if args.subfolder else CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for j, n in enumerate(args.number_of_trains):
        end_time = n * args.time_window_per_train
        for matching in args.matchings:
            for i in range(args.number_of_instances):
                seed = args.seed * (j + i + 1)
                config = {
                    "location": "KleineBinckhorst",
                    "number_of_trains": n,
                    "start_time": 0,
                    "end_time": end_time,
                    "seed": seed,
                    "use_default_material": True,
                    "trains_given": False,
                    "perform_servicing": args.perform_servicing,
                    "mixed_traffic": args.mixed_traffic,
                    "matching": MATCHING_NAME_TO_ID[matching],
                    "min_gap_on_gateway": args.min_gap_on_gateway,
                    "gateway": {
                        "arrival": [15],
                        "departure": [15],
                    },
                    "train_unit_distribution": {
                        "train_unit_types": args.train_unit_types,
                        "super_type_ratio": args.super_type_ratio,
                        "units_per_composition": args.units_per_composition,
                        "matching_complexity": args.matching_complexity,
                        "instanding_ratio": args.instanding_ratio,
                        "outstanding_ratio": args.outstanding_ratio,
                    },
                }

                out_name = f"scenario_config_custom_{n}_{matching}_{i}.json"
                out_path = config_dir / out_name
                with open(out_path, "w") as f:
                    json.dump(config, f, indent=4)
                written += 1

    print(f"Wrote {written} config(s) to {config_dir.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
