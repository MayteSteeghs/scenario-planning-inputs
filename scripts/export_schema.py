"""Export JSON Schema from the Pydantic interchange models.

Regenerates the schema/*.json files checked into this repo from the models
in src/models/. Run after any change to a model that affects the wire
schema (new/renamed/removed field, changed type, etc.):

    python3 scripts/export_schema.py

The output is the interchange contract published for robust-rail-solver
(HIP) and robust-rail-evaluator (TORS) to consume/validate against.
"""

import json
import os
import sys

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")
SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "..", "schema")
sys.path.insert(0, SRC_DIR)

from pydantic import TypeAdapter
from pydantic.json_schema import models_json_schema

from robust_rail_models import Location, Plan, Scenario, ScenarioConfig

TITLE = "Robust Rail Interchange Schema"
DESCRIPTION = (
    "JSON Schema for interchange between robust-rail-generator, "
    "robust-rail-solver, and robust-rail-evaluator. Generated from Pydantic "
    "models in robust-rail-general. Do not edit by hand."
)


def write(path: str, schema: dict) -> None:
    with open(path, "w") as f:
        json.dump(schema, f, indent=2)
        f.write("\n")
    print(f"Wrote {path}")


def main() -> None:
    write(os.path.join(SCHEMA_DIR, "schema_location.json"), Location.model_json_schema())
    write(os.path.join(SCHEMA_DIR, "schema_scenario.json"), Scenario.model_json_schema())
    write(os.path.join(SCHEMA_DIR, "schema_plan.json"), Plan.model_json_schema())

    # ScenarioConfig is a discriminated union rather than a single model, so it
    # goes through TypeAdapter. It is also generator input rather than
    # interchange, which is why it stays out of the combined schema below.
    write(
        os.path.join(SCHEMA_DIR, "schema_scenario_config.json"),
        TypeAdapter(ScenarioConfig).json_schema(),
    )

    mapping, combined = models_json_schema(
        [(Location, "validation"), (Scenario, "validation"), (Plan, "validation")],
        title=TITLE,
        description=DESCRIPTION,
    )
    combined = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": TITLE,
        "description": DESCRIPTION,
        "$defs": combined["$defs"],
        "oneOf": [mapping[(model, "validation")] for model in (Location, Scenario, Plan)],
    }
    write(os.path.join(SCHEMA_DIR, "schema_combined.json"), combined)


if __name__ == "__main__":
    main()
