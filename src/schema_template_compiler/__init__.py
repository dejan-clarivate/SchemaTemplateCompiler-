"""Public API for the shared schema-template compiler."""

from .compiler import (
    DEFAULT_SENTINEL,
    PATTERNS_FILENAME,
    SENTINEL_INSTRUCTION,
    compile_file,
    compile_schema,
    load_patterns,
    resolve_pattern,
    schema_fingerprint,
    schema_mode,
)

__all__ = [
    "DEFAULT_SENTINEL",
    "PATTERNS_FILENAME",
    "SENTINEL_INSTRUCTION",
    "compile_file",
    "compile_schema",
    "load_patterns",
    "resolve_pattern",
    "schema_fingerprint",
    "schema_mode",
]
