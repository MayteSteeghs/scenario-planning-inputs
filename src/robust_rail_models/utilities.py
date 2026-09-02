import json
import logging

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Independent monotonic integer, decoupled from tool release versions.
# Increments only on breaking schema changes. See SCHEMA_CHANGELOG.md.
EXPECTED_SCHEMA_VERSION = 1


class RailModel(BaseModel):
    """Base class for all interchange models.

    Forbids extra fields by default so that schema violations are caught
    at parse time rather than silently ignored. Use model_config to override
    in subclasses where forward-compatibility requires laxer reading.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def to_dict(self) -> dict:
        """Serialise to a dictionary suitable for JSON interchange.

        Uses camelCase field names (by_alias=True) and omits fields that
        were never explicitly set (exclude_unset=True), so optional fields
        absent from the original data do not appear as null or empty lists.
        """
        return self.model_dump(by_alias=True, exclude_unset=True)

    def to_json(self, **kwargs) -> str:
        """Serialise to a JSON string suitable for interchange.

        Accepts any keyword arguments supported by model_dump_json, but
        always applies by_alias=True and exclude_unset=True.
        """
        return self.model_dump_json(by_alias=True, exclude_unset=True, **kwargs)


class SchemaVersioned(RailModel):
    """Mixin for the top-level interchange models (Location, Scenario, Plan)
    that carry the shared schemaVersion.

    All three carry the same value and bump together on a breaking change;
    see SCHEMA_CHANGELOG.md for what changed at each version. schemaVersion
    is always emitted on serialisation, even by subclasses that otherwise
    omit fields that were never explicitly set. A missing or unexpected
    value when reading external JSON produces a logged warning; parsing
    proceeds regardless (warn-and-continue, no hard reject). Objects built
    directly in Python (rather than parsed from a dict) are always assumed
    current and never warn, so callers don't need to pass schema_version.
    """

    schema_version: int = Field(EXPECTED_SCHEMA_VERSION, alias="schemaVersion")

    @classmethod
    def model_validate(cls, obj, **kwargs):
        if isinstance(obj, dict) and "schemaVersion" not in obj and "schema_version" not in obj:
            logging.warning(f"{cls.__name__}: schemaVersion is missing; assuming {EXPECTED_SCHEMA_VERSION}.")
        return super().model_validate(obj, **kwargs)

    @model_validator(mode="after")
    def _warn_on_schema_version_mismatch(self) -> "SchemaVersioned":
        if self.schema_version != EXPECTED_SCHEMA_VERSION:
            logging.warning(
                f"{type(self).__name__}: schemaVersion {self.schema_version} "
                f"does not match expected {EXPECTED_SCHEMA_VERSION}."
            )
        return self

    def to_dict(self) -> dict:
        data = super().to_dict()
        data["schemaVersion"] = self.schema_version
        return data

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), **kwargs)


class TimeInterval(RailModel):
    """A single time interval, with times in seconds since the epoch."""

    start: float
    end: float
