# Schema Template Compiler

`schema-template-compiler` converts example-shaped JSON templates into strict,
nullable Draft 2020-12 JSON Schemas suitable for structured model output.

It is the shared compiler for UniversalPdfParser and MarkBench. The package
supports:

- nested objects and typed example values;
- required properties and `additionalProperties: false`;
- non-nullable objects and arrays, so a declared structure is always returned
  with its keys and absence is expressed on the leaves;
- descriptions from non-empty string values;
- `$`-prefixed constraint specifications;
- fields that take one of several types, such as a string or an array of strings;
- reusable named patterns such as `@date_iso`;
- project-specific `_patterns.json` overrides;
- an absence sentinel compatible with constrained decoding;
- pass-through and validation of advanced JSON Schemas.

## Install

```powershell
pip install git+https://github.com/dejan-clarivate/SchemaTemplateCompiler-.git@v0.2.0
```

For development from a local checkout:

```powershell
pip install -e C:\projects\SchemaTemplateCompiler
```

## Python API

```python
from schema_template_compiler import compile_schema

mode, schema = compile_schema(
    {"filed_date": {"$pattern": "@date_iso"}}
)
```

An exact constant value can be declared with `$const`:

```python
mode, schema = compile_schema(
    {"Translators note": {"$const": "not found"}}
)
```

A list of types in `$type` lets a field take any of them, compiled to `anyOf`.
With `"array"` in the list, the field may also be a list of the other types:

```python
mode, schema = compile_schema(
    {"Applicant Name": {"$type": ["string", "array"]}}
)
# "Applicant Name": "5 RIVERS INC"  or  ["Gold Star Mortgage", "Radiant Mortgage, LLC"]
```

The other `$` keys (`$pattern`, `$enum`, `$minimum`, ...) constrain each
value, whether it stands alone or is an array item; `$minItems` and `$maxItems`
constrain the array. Objects cannot be part of a type list.

`@date_iso` resolves to `^\\d{4}-\\d{2}-\\d{2}$`. String patterns also admit
the default absence sentinel, so the resulting pattern ends with
`|^not\ found$`.

Project-specific patterns can be supplied through a schema root containing an
`_patterns.json` file:

```python
from pathlib import Path
from schema_template_compiler import compile_schema, load_patterns

patterns = load_patterns(Path("json_schemas"))
mode, schema = compile_schema(source, patterns)
```

## CLI

```powershell
schema-template-compiler --schema-root json_schemas --output-root compiled_json_schemas
```

Files beginning with `_` are treated as support files and are not compiled as
schema templates.
