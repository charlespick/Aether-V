"""Utility helpers for loading and validating job input schemas."""
from __future__ import annotations

import copy
import ipaddress
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: Optional[Dict[str, Any]] = None

_DEFAULT_SCHEMA_PATH_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "Schemas" / "job-inputs.yaml",
    Path(__file__).resolve().parents[3] / "Schemas" / "job-inputs.yaml",
]

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
    if path:
        schema_path = Path(path)
    else:
        for candidate in _DEFAULT_SCHEMA_PATH_CANDIDATES:
            if candidate.exists():
                schema_path = candidate
                break
        else:
            schema_path = _DEFAULT_SCHEMA_PATH_CANDIDATES[0]

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

        hint = entry.get("hint")
        if hint is not None and not isinstance(hint, str):
            raise SchemaValidationError([f"Field '{fid}' hint must be a string when provided"])

    for param_set in raw.get("parameter_sets", []) or []:
        if not isinstance(param_set, dict):
            raise SchemaValidationError(["Parameter set definitions must be mappings"])

        members = param_set.get("members")
        variants = param_set.get("variants")

        if members and variants:
            raise SchemaValidationError(
                [
                    f"Parameter set '{param_set.get('id', '?')}' cannot define both 'members' and 'variants'"
                ]
            )

        if members is not None:
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
            continue

        if variants is None:
            raise SchemaValidationError(
                [
                    f"Parameter set '{param_set.get('id', '?')}' must define either 'members' or 'variants'"
                ]
            )

        if not isinstance(variants, list) or not variants:
            raise SchemaValidationError(
                [
                    f"Parameter set '{param_set.get('id', '?')}' must provide at least one variant definition"
                ]
            )

        for variant in variants:
            if not isinstance(variant, dict):
                raise SchemaValidationError(
                    [
                        f"Parameter set '{param_set.get('id', '?')}' variants must be mappings"
                    ]
                )
            required = variant.get("required", [])
            optional = variant.get("optional", [])
            if not isinstance(required, list):
                raise SchemaValidationError(
                    [
                        f"Parameter set '{param_set.get('id', '?')}' variant 'required' must be a list"
                    ]
                )
            if not required:
                raise SchemaValidationError(
                    [
                        f"Parameter set '{param_set.get('id', '?')}' variant must require at least one field"
                    ]
                )
            if optional is not None and not isinstance(optional, list):
                raise SchemaValidationError(
                    [
                        f"Parameter set '{param_set.get('id', '?')}' variant 'optional' must be a list when provided"
                    ]
                )
            missing_required = [member for member in required if member not in field_ids]
            missing_optional = [member for member in (optional or []) if member not in field_ids]
            missing = missing_required + missing_optional
            if missing:
                raise SchemaValidationError(
                    [
                        f"Parameter set '{param_set.get('id', '?')}' references unknown fields: "
                        + ", ".join(missing)
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
        members: Optional[List[str]] = param_set.get("members")
        mode = (param_set.get("mode") or "").lower()
        variants = param_set.get("variants")

        if members is not None:
            provided_members = [m for m in members if not _is_missing(sanitized.get(m))]
            if mode == "all-or-none" and provided_members and len(provided_members) != len(members):
                missing_members = [m for m in members if _is_missing(sanitized.get(m))]
                label = param_set.get("label") or param_set.get("id", "parameter set")
                errors.append(
                    f"Parameter set '{label}' requires all members: {', '.join(missing_members)}"
                )
            continue

        if variants:
            all_variant_fields = set()
            for variant in variants:
                required_fields = variant.get("required", []) or []
                optional_fields = variant.get("optional", []) or []
                all_variant_fields.update(required_fields)
                all_variant_fields.update(optional_fields)

            provided_variant_fields = [
                field for field in all_variant_fields if not _is_missing(sanitized.get(field))
            ]

            if not provided_variant_fields:
                continue

            matched_variant = False
            for variant in variants:
                required_fields = variant.get("required", []) or []
                optional_fields = variant.get("optional", []) or []

                missing_required = [
                    field for field in required_fields if _is_missing(sanitized.get(field))
                ]
                if missing_required:
                    continue

                allowed_fields = set(required_fields) | set(optional_fields)
                extra_fields = [
                    field for field in provided_variant_fields if field not in allowed_fields
                ]
                if extra_fields:
                    continue

                matched_variant = True
                break

            if not matched_variant:
                label = param_set.get("label") or param_set.get("id", "parameter set")
                variant_descriptions = []
                for variant in variants:
                    variant_label = variant.get("label")
                    required_fields = variant.get("required", []) or []
                    optional_fields = variant.get("optional", []) or []
                    parts: List[str] = []
                    if variant_label:
                        parts.append(variant_label)
                    if required_fields:
                        parts.append("required: " + ", ".join(required_fields))
                    if optional_fields:
                        parts.append("optional: " + ", ".join(optional_fields))
                    variant_descriptions.append("; ".join(parts) if parts else "<unspecified variant>")

                errors.append(
                    f"Parameter set '{label}' must satisfy one of the allowed variants: "
                    + " | ".join(variant_descriptions)
                )

    if errors:
        raise SchemaValidationError(errors)

    cleaned = {
        field_id: value
        for field_id, value in sanitized.items()
        if not _is_missing(value)
    }

    return cleaned


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


def get_sensitive_field_ids(schema: Optional[Dict[str, Any]] = None) -> Set[str]:
    """Return the set of schema field ids that should be treated as sensitive."""

    schema_data = schema or get_job_schema()
    fields = schema_data.get("fields", []) if isinstance(schema_data, dict) else []
    sensitive_types = {"secret"}
    sensitive: Set[str] = set()

    for field in fields:
        if not isinstance(field, dict):
            continue
        field_type = str(field.get("type", "")).lower()
        if field_type in sensitive_types or field.get("secret") is True:
            fid = field.get("id")
            if isinstance(fid, str) and fid:
                sensitive.add(fid)

    return sensitive


def redact_job_parameters(
    parameters: Optional[Dict[str, Any]],
    schema: Optional[Dict[str, Any]] = None,
    replacement: str = "••••••",
) -> Dict[str, Any]:
    """Return a copy of job parameters with sensitive values removed."""

    if parameters is None:
        return {}

    sanitized = copy.deepcopy(parameters)
    sensitive_keys = get_sensitive_field_ids(schema)

    if not sensitive_keys:
        return sanitized

    def _redact(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in sensitive_keys and item is not None:
                    value[key] = replacement
                else:
                    _redact(item)
        elif isinstance(value, list):
            for element in value:
                _redact(element)

    _redact(sanitized)
    return sanitized
