"""Compile example-shaped templates into strict Draft 2020-12 JSON Schemas."""

from __future__ import annotations

import argparse
from importlib.resources import files
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from jsonschema import Draft202012Validator


JSON_SCHEMA_TYPES = {"null", "boolean", "object", "array", "number", "string", "integer"}
ADVANCED_KEYWORDS = {
    "$schema", "$id", "$ref", "$defs", "properties", "required",
    "additionalProperties", "allOf", "anyOf", "oneOf", "not", "if", "then",
    "else", "dependentSchemas", "patternProperties",
}
SPEC_KEYS = {
    "$type": "type", "$description": "description", "$pattern": "pattern",
    "$format": "format", "$enum": "enum", "$const": "const", "$minimum": "minimum",
    "$maximum": "maximum", "$exclusiveMinimum": "exclusiveMinimum",
    "$exclusiveMaximum": "exclusiveMaximum", "$multipleOf": "multipleOf",
    "$minItems": "minItems", "$maxItems": "maxItems",
}
# Types a "$type" list may combine; objects need fields, so they stay out
UNION_TYPES = ("string", "integer", "number", "boolean", "array")
PATTERNS_FILENAME = "_patterns.json"
DEFAULT_SENTINEL = "not found"
SENTINEL_INSTRUCTION = (
    'If a string field is absent from the document or illegible, return "not found". '
    "Never guess or invent a value."
)


def schema_mode(source: dict[str, Any]) -> str:
    """Return ``advanced`` for JSON Schema input and ``simple`` for a template."""
    if any(keyword in source for keyword in ADVANCED_KEYWORDS):
        return "advanced"
    declared_type = source.get("type")
    if isinstance(declared_type, str) and declared_type in JSON_SCHEMA_TYPES:
        return "advanced"
    if isinstance(declared_type, list) and declared_type and all(
        item in JSON_SCHEMA_TYPES for item in declared_type
    ):
        return "advanced"
    return "simple"


def _read_patterns_file(patterns_path: Path) -> dict[str, str]:
    with patterns_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()
    ):
        raise ValueError(f"{patterns_path} must map pattern names to regex strings")
    return loaded


def _builtin_patterns() -> dict[str, str]:
    resource = files("schema_template_compiler").joinpath("patterns.json")
    loaded = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()
    ):
        raise ValueError("Packaged patterns.json must map pattern names to regex strings")
    return loaded


def load_patterns(schema_root: Path | None = None) -> dict[str, str]:
    """Load built-ins and merge a schema root's ``_patterns.json`` over them."""
    patterns = _builtin_patterns()
    if schema_root is not None:
        patterns_path = Path(schema_root) / PATTERNS_FILENAME
        if patterns_path.exists():
            patterns.update(_read_patterns_file(patterns_path))
    return patterns


def resolve_pattern(value: str, patterns: Mapping[str, str], path: str) -> str:
    """Resolve an ``@name`` reference; return literal regular expressions unchanged."""
    if not value.startswith("@"):
        return value
    name = value[1:]
    if name not in patterns:
        raise ValueError(
            f"Unknown named pattern '@{name}' at {path}. "
            f"Available: {', '.join(sorted(patterns))}"
        )
    return patterns[name]


def compile_schema(
    source: dict[str, Any], patterns: Mapping[str, str] | None = None
) -> tuple[str, dict[str, Any]]:
    """Compile and validate a source schema, returning mode and effective schema."""
    if not isinstance(source, dict):
        raise ValueError("Schema source must contain a JSON object")
    mode = schema_mode(source)
    if mode == "advanced":
        effective = source
    else:
        if not source:
            raise ValueError("Simple template must contain at least one field")
        effective = _compile_object(
            source, "$", False, patterns if patterns is not None else load_patterns()
        )
        effective["description"] = SENTINEL_INSTRUCTION
    try:
        Draft202012Validator.check_schema(effective)
    except Exception as error:
        message = getattr(error, "message", str(error))
        raise ValueError(f"Invalid {mode} schema: {message}") from error
    return mode, effective


def _compile_object(
    value: dict[str, Any], path: str, nullable: bool, patterns: Mapping[str, str]
) -> dict[str, Any]:
    """Compile a nested object. Objects are never nullable: a null object erases
    its declared keys, so an absent block must still be returned as the full
    structure whose leaves carry the absence sentinel."""
    del nullable
    properties: dict[str, Any] = {}
    required: list[str] = []
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"Simple schema at {path} contains an empty field name")
        properties[key] = _compile_value(item, f"{path}.{key}", True, patterns)
        required.append(key)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _compile_spec(
    value: dict[str, Any], path: str, nullable: bool, patterns: Mapping[str, str]
) -> dict[str, Any]:
    unknown = [key for key in value if key not in SPEC_KEYS and key != "$default"]
    if unknown:
        raise ValueError(
            f"Unknown spec key(s) at {path}: {', '.join(unknown)}. "
            f"Allowed: {', '.join(SPEC_KEYS)}, $default"
        )
    base_type = value.get("$type", "string")
    if isinstance(base_type, list):
        return _compile_union(value, path, nullable, patterns)
    if base_type in ("object", "array"):
        nullable = False
    prop: dict[str, Any] = {"type": [base_type, "null"] if nullable else base_type}
    for key, item in value.items():
        if key not in ("$type", "$default"):
            prop[SPEC_KEYS[key]] = item
    if isinstance(prop.get("pattern"), str):
        prop["pattern"] = resolve_pattern(prop["pattern"], patterns, path)
    if "pattern" in prop and base_type == "string":
        sentinel = value.get("$default", DEFAULT_SENTINEL)
        if sentinel is not None:
            prop["pattern"] += f"|^{re.escape(sentinel)}$"
    elif "$default" in value:
        raise ValueError(f"$default at {path} only applies to string fields with a $pattern")
    return prop


def _compile_union(
    value: dict[str, Any], path: str, nullable: bool, patterns: Mapping[str, str]
) -> dict[str, Any]:
    """Compile ``"$type": [...]`` into ``anyOf``: one branch per scalar type, and
    with "array", a list of those scalars. The other spec keys constrain each
    scalar, whether it stands alone or is an array item; $minItems and $maxItems
    constrain the array."""
    types = value["$type"]
    unsupported = [item for item in types if item not in UNION_TYPES]
    if len(types) < 2 or len(set(types)) != len(types) or unsupported:
        raise ValueError(
            f"$type list at {path} must name two or more distinct types from "
            f"{', '.join(UNION_TYPES)}, got {types!r}"
        )
    scalars = [item for item in types if item != "array"]
    if not scalars:
        raise ValueError(f"$type list at {path} needs a scalar type besides 'array'")
    array_keys = {"$minItems", "$maxItems"}
    if "array" not in types and array_keys & set(value):
        raise ValueError(f"$minItems/$maxItems at {path} need 'array' in $type")

    union: dict[str, Any] = {}
    if "$description" in value:
        union["description"] = value["$description"]
    scalar_spec = {
        key: item for key, item in value.items()
        if key not in array_keys | {"$type", "$description"}
    }

    def scalar(type_name: str, scalar_nullable: bool) -> dict[str, Any]:
        return _compile_spec({**scalar_spec, "$type": type_name}, path, scalar_nullable, patterns)

    branches = [scalar(type_name, nullable) for type_name in scalars]
    if "array" in types:
        # Items are not nullable: a missing value is an empty list, as for any array
        items = [scalar(type_name, False) for type_name in scalars]
        array: dict[str, Any] = {
            "type": "array",
            "items": items[0] if len(items) == 1 else {"anyOf": items},
        }
        for key in sorted(array_keys & set(value)):
            array[SPEC_KEYS[key]] = value[key]
        branches.append(array)
    union["anyOf"] = branches
    return union


def _compile_value(
    value: Any, path: str, nullable: bool, patterns: Mapping[str, str]
) -> dict[str, Any]:
    if isinstance(value, str):
        prop: dict[str, Any] = {"type": ["string", "null"] if nullable else "string"}
        if value.strip():
            prop["description"] = value.strip()
        return prop
    if isinstance(value, bool):
        return {"type": ["boolean", "null"] if nullable else "boolean"}
    if isinstance(value, int):
        return {"type": ["integer", "null"] if nullable else "integer"}
    if isinstance(value, float):
        return {"type": ["number", "null"] if nullable else "number"}
    if isinstance(value, dict):
        if not value:
            raise ValueError(f"Empty object at {path}: cannot infer its fields")
        if any(isinstance(key, str) and key.startswith("$") for key in value):
            return _compile_spec(value, path, nullable, patterns)
        return _compile_object(value, path, nullable, patterns)
    if isinstance(value, list):
        if len(value) > 1:
            raise ValueError(
                f"Array at {path} must contain at most one example item, got {len(value)}"
            )
        items = (
            _compile_value(value[0], f"{path}[0]", False, patterns)
            if value else {"type": "string"}
        )
        # Arrays are never nullable for the same reason as objects: an empty
        # list already expresses absence without discarding the declared shape.
        return {"type": "array", "items": items}
    if value is None:
        raise ValueError(f"Null at {path}: type is ambiguous, use '' or 0 instead")
    raise ValueError(f"Unsupported template value at {path}: {value!r}")


def schema_fingerprint(schema: dict[str, Any]) -> str:
    """Return a deterministic compact representation suitable for hashing."""
    return json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compile_file(
    source_path: Path,
    output_root: Path,
    schema_root: Path,
    patterns: Mapping[str, str] | None = None,
) -> tuple[str, Path]:
    """Compile one JSON file and atomically write it beneath ``output_root``."""
    with Path(source_path).open("r", encoding="utf-8") as handle:
        source = json.load(handle)
    mode, schema = compile_schema(
        source, patterns if patterns is not None else load_patterns(schema_root)
    )
    output_path = Path(output_root) / Path(source_path).relative_to(schema_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(schema, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    temporary.replace(output_path)
    return mode, output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--schema-root", type=Path, default=Path("json_schemas"))
    parser.add_argument("--output-root", type=Path, default=Path("compiled_json_schemas"))
    args = parser.parse_args(argv)
    paths = args.paths or sorted(
        path for path in args.schema_root.rglob("*.json") if not path.name.startswith("_")
    )
    if not paths:
        parser.error(f"No *.json files found under {args.schema_root}")
    patterns = load_patterns(args.schema_root)
    failures = 0
    for path in paths:
        try:
            mode, output_path = compile_file(path, args.output_root, args.schema_root, patterns)
            print(f"[{mode}] {path} -> {output_path}")
        except (ValueError, json.JSONDecodeError) as error:
            failures += 1
            print(f"[error] {path}: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
