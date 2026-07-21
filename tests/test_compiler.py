from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from schema_template_compiler import compile_file, compile_schema, load_patterns, schema_fingerprint


class SchemaTemplateCompilerTests(unittest.TestCase):
    def test_compiles_nested_simple_template(self):
        mode, schema = compile_schema({
            "mark_name": "", "owner": {"name": ""},
            "nice_classes": [0], "active": False,
        })
        self.assertEqual(mode, "simple")
        self.assertEqual(schema["properties"]["mark_name"]["type"], ["string", "null"])
        self.assertEqual(schema["properties"]["owner"]["type"], ["object", "null"])
        self.assertEqual(schema["properties"]["nice_classes"]["items"]["type"], "integer")
        self.assertEqual(schema["required"], ["mark_name", "owner", "nice_classes", "active"])
        self.assertFalse(schema["additionalProperties"])

    def test_descriptions_and_empty_arrays(self):
        _, schema = compile_schema({"name": "Read the printed name.", "history": []})
        self.assertEqual(schema["properties"]["name"]["description"], "Read the printed name.")
        self.assertEqual(schema["properties"]["history"]["items"], {"type": "string"})

    def test_named_date_iso_pattern_and_sentinel(self):
        _, schema = compile_schema({"filed_date": {"$pattern": "@date_iso"}})
        self.assertEqual(
            schema["properties"]["filed_date"]["pattern"],
            r"^\d{4}-\d{2}-\d{2}$|^not\ found$",
        )

    def test_project_patterns_override_builtins(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "_patterns.json").write_text(
                json.dumps({"date_iso": "^CUSTOM$", "docket": "^D-[0-9]+$"}),
                encoding="utf-8",
            )
            patterns = load_patterns(root)
            self.assertEqual(patterns["date_iso"], "^CUSTOM$")
            self.assertEqual(patterns["docket"], "^D-[0-9]+$")
            self.assertIn("zip_code", patterns)

    def test_constraint_spec(self):
        _, schema = compile_schema({
            "class": {"$type": "integer", "$minimum": 1, "$maximum": 45},
            "kind": {"$enum": ["Trademark", "Service Mark"]},
        })
        self.assertEqual(schema["properties"]["class"]["minimum"], 1)
        self.assertEqual(schema["properties"]["kind"]["enum"], ["Trademark", "Service Mark"])

    def test_preserves_and_validates_advanced_schema(self):
        source = {"type": "object", "properties": {"name": {"type": "string"}}}
        mode, schema = compile_schema(source)
        self.assertEqual(mode, "advanced")
        self.assertIs(schema, source)
        with self.assertRaisesRegex(ValueError, "Invalid advanced schema"):
            compile_schema({"type": "object", "properties": []})

    def test_detects_ref_only_advanced_schema(self):
        source = {"$ref": "#/$defs/name", "$defs": {"name": {"type": "string"}}}
        self.assertEqual(compile_schema(source), ("advanced", source))

    def test_rejects_ambiguous_values_and_unknown_patterns(self):
        with self.assertRaisesRegex(ValueError, r"Null at \$\.status"):
            compile_schema({"status": None})
        with self.assertRaisesRegex(ValueError, "must contain at most one"):
            compile_schema({"classes": ["one", "two"]})
        with self.assertRaisesRegex(ValueError, "Unknown named pattern '@missing'"):
            compile_schema({"date": {"$pattern": "@missing"}})

    def test_compile_file_and_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema_root = root / "schemas"
            source = schema_root / "state" / "registration.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"date": {"$pattern": "@date_iso"}}', encoding="utf-8")
            mode, output = compile_file(source, root / "compiled", schema_root)
            self.assertEqual(mode, "simple")
            self.assertEqual(output, root / "compiled" / "state" / "registration.json")
            self.assertIn("pattern", json.loads(output.read_text(encoding="utf-8"))["properties"]["date"])
        self.assertEqual(schema_fingerprint({"b": 2, "a": 1}), schema_fingerprint({"a": 1, "b": 2}))


if __name__ == "__main__":
    unittest.main()
