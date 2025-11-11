from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple, get_args, get_origin

import pytest

from app.core.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO_ROOT / "server" / ".env.example"
CONFIGMAP = REPO_ROOT / "server" / "k8s" / "configmap.yaml"
DOC_CONFIG = REPO_ROOT / "Docs" / "Configuration.md"


def collect_settings_metadata() -> Dict[str, Dict[str, Any]]:
    metadata: Dict[str, Dict[str, Any]] = {}
    for name, field in Settings.model_fields.items():
        env_name = (field.alias or name).upper()
        annotation = field.annotation
        optional = False
        if annotation is not None:
            origin = get_origin(annotation)
            if origin is not None:
                optional = type(None) in get_args(annotation)
        default = field.default
        metadata[env_name] = {
            "field_name": name,
            "annotation": annotation,
            "default": default,
            "optional": optional,
        }
    return metadata


def parse_env_example(path: Path) -> Dict[str, Dict[str, Any]]:
    data: Dict[str, Dict[str, Any]] = {}
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if "=" not in stripped:
            continue
        commented = stripped.startswith("#")
        line = stripped.lstrip("#").strip()
        if "=" not in line:
            continue
        key, rest = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z0-9_]+", key):
            continue
        value = rest.split("#", 1)[0].strip()
        data.setdefault(key, {"commented": commented, "value": value})
    return data


def parse_configmap(path: Path) -> Dict[str, Dict[str, Any]]:
    data: Dict[str, Dict[str, Any]] = {}
    for raw_line in path.read_text().splitlines():
        stripped = raw_line.strip()
        if ":" not in stripped:
            continue
        commented = stripped.startswith("#")
        line = stripped.lstrip("#").strip()
        if ":" not in line:
            continue
        key_part, rest = line.split(":", 1)
        key = key_part.strip()
        if not re.fullmatch(r"[A-Z0-9_]+", key):
            continue
        value = rest.split("#", 1)[0].strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        data.setdefault(key, {"commented": commented, "value": value})
    return data


def parse_markdown_table(lines: Iterable[str], start_token: str) -> Tuple[Dict[str, Dict[str, str]], int]:
    rows: Dict[str, Dict[str, str]] = {}
    header: Tuple[str, ...] | None = None
    start_index = None
    for idx, line in enumerate(lines):
        if line.strip().startswith(start_token):
            start_index = idx
            break
    if start_index is None:
        return rows, len(list(lines))

    for offset, line in enumerate(lines[start_index:], start=start_index):
        stripped = line.strip()
        if not stripped:
            if header is not None:
                return rows, offset
            continue
        if not stripped.startswith("|"):
            if header is not None:
                return rows, offset
            continue
        parts = [part.strip() for part in stripped.strip("|").split("|")]
        if header is None:
            header = tuple(parts)
            continue
        if all(set(part) <= {"-", ":", " "} for part in parts):
            continue
        row = {header[i]: parts[i] if i < len(parts) else "" for i in range(len(header))}
        key = row.get("Variable")
        if key:
            rows[key.strip("`")] = row
    return rows, offset  # pragma: no cover - loop should exit earlier


def load_documentation() -> Tuple[Dict[str, Dict[str, str]], Dict[str, Dict[str, str]]]:
    lines = DOC_CONFIG.read_text().splitlines()
    non_secret_rows, stop_index = parse_markdown_table(lines, "| Variable")
    secret_rows, _ = parse_markdown_table(lines[stop_index:], "| Variable")
    return non_secret_rows, secret_rows


SETTINGS_METADATA = collect_settings_metadata()
DOC_NON_SECRET, DOC_SECRET = load_documentation()
ENV_EXAMPLE_DATA = parse_env_example(ENV_EXAMPLE)
CONFIGMAP_DATA = parse_configmap(CONFIGMAP)

def metadata_default_to_doc_string(default: Any) -> str:
    if default is None:
        return "_(unset)_"
    if isinstance(default, bool):
        return "true" if default else "false"
    if isinstance(default, (int, float)):
        return str(default)
    if isinstance(default, str):
        if default == "":
            return "_(empty)_"
        return default
    return str(default)


def normalize_doc_default(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("`") and cleaned.endswith("`"):
        cleaned = cleaned[1:-1]
    cleaned = cleaned.strip()
    if cleaned.lower() in {"_(unset)_", "_(empty)_"}:
        return cleaned.lower()
    cleaned = cleaned.replace("\\\\", "\\")
    return cleaned


def is_doc_required(text: str) -> bool:
    lowered = text.lower()
    return "yes" in lowered or "required" in lowered


@pytest.mark.parametrize("env_var", sorted(SETTINGS_METADATA.keys()))
def test_configuration_surface_consistency(env_var: str) -> None:
    metadata = SETTINGS_METADATA
    non_secret_rows = DOC_NON_SECRET
    secret_rows = DOC_SECRET
    env_example = ENV_EXAMPLE_DATA
    configmap = CONFIGMAP_DATA

    secret_vars = set(secret_rows)
    doc_vars = set(non_secret_rows) | secret_vars

    assert doc_vars == set(metadata), "Documentation variables do not match Settings fields"

    field_meta = metadata[env_var]
    default = metadata_default_to_doc_string(field_meta["default"])

    if env_var in secret_vars:
        assert env_var in env_example, f"{env_var} missing from .env example"
        assert env_var not in configmap, f"Secret {env_var} should not appear in ConfigMap"
        return

    assert env_var in non_secret_rows, f"{env_var} missing from documentation table"
    doc_row = non_secret_rows[env_var]
    doc_default = normalize_doc_default(doc_row.get("Default", ""))
    if default in {"_(unset)_", "_(empty)_"}:
        assert doc_default == default.lower(), f"Default for {env_var} mismatched in documentation"
    else:
        assert doc_default == default, f"Default for {env_var} mismatched in documentation"

    assert env_var in env_example, f"{env_var} missing from .env example"
    env_entry = env_example[env_var]

    required = is_doc_required(doc_row.get("Required?", ""))
    if required:
        assert not env_entry["commented"], f"Required variable {env_var} should not be commented in .env example"
    else:
        assert env_entry["commented"], f"Optional variable {env_var} should be commented out in .env example"

    assert env_var in configmap, f"{env_var} missing from ConfigMap"
    config_entry = configmap[env_var]
    if required:
        assert not config_entry["commented"], f"Required variable {env_var} should not be commented in ConfigMap"
    else:
        assert config_entry["commented"], f"Optional variable {env_var} should be commented out in ConfigMap"
