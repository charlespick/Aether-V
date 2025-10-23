"""Utility helpers for loading and validating job input schemas."""
from __future__ import annotations

import ipaddress
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: Optional[Dict[str, Any]] = None

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "Schemas" / "job-inputs.yaml"

_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,255}$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_IPV4_INPUT_PATTERN = r"^(?:\d{1,3}\.){3}\d{1,3}$"


class SchemaValidationError(Exception):
    """Raised when a schema or submission fails validation."""

    def __init__(self, errors: Iterable[str]):
        messages = [str(e) for e in errors if str(e)]
        if not messages:
            messages = ["Unknown schema validation error"]
        self.errors = messages
        super().__init__("; ".join(messages))


def load_job_schema(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load and validate the job input schema from disk."""

    global _SCHEMA_CACHE
    schema_path = Path(path) if path else DEFAULT_SCHEMA_PATH

    if not schema_path.exists():
        raise SchemaValidationError([f"Schema file not found: {schema_path}"])

    with schema_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise SchemaValidationError(["Schema root must be a mapping"])

    required_top_level = {"version", "fields"}
    missing = required_top_level - raw.keys()
    if missing:
        raise SchemaValidationError([f"Schema missing required keys: {', '.join(sorted(missing))}"])

    if not isinstance(raw["fields"], list) or not raw["fields"]:
        raise SchemaValidationError(["Schema must define at least one field"])

    field_ids = set()
    for entry in raw["fields"]:
        if not isinstance(entry, dict):
            raise SchemaValidationError(["Each field definition must be a mapping"])
        fid = entry.get("id")
        if not fid:
            raise SchemaValidationError(["Field definition missing 'id'"])
        if fid in field_ids:
            raise SchemaValidationError([f"Duplicate field id: {fid}"])
        field_ids.add(fid)

        field_type = (entry.get("type") or "string").lower()
        if field_type == "ipv4":
            validations = entry.get("validations") or {}
            if "pattern" not in validations:
                validations["pattern"] = _IPV4_INPUT_PATTERN
            entry["validations"] = validations

    for param_set in raw.get("parameter_sets", []) or []:
        if not isinstance(param_set, dict):
            raise SchemaValidationError(["Parameter set definitions must be mappings"])
        members = param_set.get("members", [])
        if not isinstance(members, list) or not members:
            raise SchemaValidationError(
                [f"Parameter set '{param_set.get('id', '?')}' must list at least one member"]
            )
        missing_members = [member for member in members if member not in field_ids]
        if missing_members:
            raise SchemaValidationError(
                [
                    f"Parameter set '{param_set.get('id', '?')}' references unknown fields: "
                    + ", ".join(missing_members)
                ]
            )

    _SCHEMA_CACHE = raw
    logger.info(
        "Loaded job input schema '%s' version %s", raw.get("id", "default"), raw["version"]
    )
    return raw


def get_job_schema() -> Dict[str, Any]:
    """Return the cached job input schema, loading it if required."""

    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        return load_job_schema()
    return _SCHEMA_CACHE


def validate_job_submission(values: Dict[str, Any], schema: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate user supplied values against the schema."""

    schema_data = schema or get_job_schema()
    field_map = {field["id"]: field for field in schema_data.get("fields", [])}
    errors: List[str] = []
    sanitized: Dict[str, Any] = {}

    unknown_fields = sorted(set(values.keys()) - set(field_map.keys()))
    if unknown_fields:
        errors.append("Unknown field(s): " + ", ".join(unknown_fields))

    for field_id, field in field_map.items():
        raw_value = values.get(field_id, None)
        if _is_missing(raw_value):
            if "default" in field:
                sanitized[field_id] = field["default"]
            elif field.get("required", False):
                errors.append(f"Field '{field_id}' is required")
                sanitized[field_id] = None
            else:
                sanitized[field_id] = None
            continue

        try:
            sanitized[field_id] = _coerce_and_validate(field, raw_value)
        except ValueError as exc:  # pragma: no cover - defensive
            errors.append(str(exc))
            sanitized[field_id] = None

    for param_set in schema_data.get("parameter_sets", []) or []:
        members: List[str] = param_set.get("members", [])
        mode = (param_set.get("mode") or "").lower()
        provided_members = [m for m in members if not _is_missing(sanitized.get(m))]
        if mode == "all-or-none" and provided_members and len(provided_members) != len(members):
            missing_members = [m for m in members if _is_missing(sanitized.get(m))]
            label = param_set.get("label") or param_set.get("id", "parameter set")
            errors.append(
                f"Parameter set '{label}' requires all members: {', '.join(missing_members)}"
            )

    if errors:
        raise SchemaValidationError(errors)

    return sanitized


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _coerce_and_validate(field: Dict[str, Any], value: Any) -> Any:
    field_type = (field.get("type") or "string").lower()
    field_id = field.get("id", "field")

    if field_type in {"string", "secret"}:
        text = str(value).strip()
        _validate_string_lengths(field, text)
        return text

    if field_type == "multiline":
        text = str(value)
        _validate_string_lengths(field, text)
        return text

    if field_type == "integer":
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"Field '{field_id}' must be an integer") from None
        validations = field.get("validations", {}) or {}
        minimum = validations.get("minimum")
        maximum = validations.get("maximum")
        if minimum is not None and parsed < minimum:
            raise ValueError(f"Field '{field_id}' must be >= {minimum}")
        if maximum is not None and parsed > maximum:
            raise ValueError(f"Field '{field_id}' must be <= {maximum}")
        return parsed

    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"Field '{field_id}' must be a boolean")

    if field_type == "ipv4":
        try:
            return str(ipaddress.IPv4Address(str(value).strip()))
        except ipaddress.AddressValueError:
            raise ValueError(f"Field '{field_id}' must be a valid IPv4 address") from None

    if field_type == "hostname":
        text = str(value).strip()
        if not _HOSTNAME_PATTERN.fullmatch(text):
            raise ValueError(f"Field '{field_id}' must be a valid hostname")
        return text

    # Fallback: return value unchanged
    return value


def _validate_string_lengths(field: Dict[str, Any], value: str) -> None:
    validations = field.get("validations", {}) or {}
    min_length = validations.get("min_length")
    max_length = validations.get("max_length")
    field_id = field.get("id", "field")

    if min_length is not None and len(value) < min_length:
        raise ValueError(f"Field '{field_id}' must be at least {min_length} characters")
    if max_length is not None and len(value) > max_length:
        raise ValueError(f"Field '{field_id}' must be at most {max_length} characters")
