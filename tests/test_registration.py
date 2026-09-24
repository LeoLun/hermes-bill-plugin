from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


class FakeContext:
    def __init__(self):
        self.skills = []
        self.tools = []

    def register_skill(self, name, path):
        self.skills.append((name, path))

    def register_tool(self, **kwargs):
        self.tools.append(kwargs)


class RegistrationTests(unittest.TestCase):
    def test_plugin_registers_skill_and_three_tools(self):
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "hermes_bill_plugin",
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        context = FakeContext()
        module.register(context)
        self.assertEqual(context.skills[0][0], "bill-manager")
        self.assertTrue(context.skills[0][1].exists())
        self.assertEqual(
            {tool["name"] for tool in context.tools},
            {"bill_add_record", "bill_import_records", "bill_update_record"},
        )
        self.assertTrue(all(tool["toolset"] == "hermes_bill" for tool in context.tools))

    def test_tool_validation_error_is_returned_as_json(self):
        root = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(
            "hermes_bill_plugin_error_case",
            root / "__init__.py",
            submodule_search_locations=[str(root)],
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        context = FakeContext()
        module.register(context)
        add_tool = next(tool for tool in context.tools if tool["name"] == "bill_add_record")
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("HERMES_BILL_DATA_DIR")
            os.environ["HERMES_BILL_DATA_DIR"] = directory
            try:
                payload = json.loads(add_tool["handler"]({"record": {}}))
            finally:
                if previous is None:
                    os.environ.pop("HERMES_BILL_DATA_DIR", None)
                else:
                    os.environ["HERMES_BILL_DATA_DIR"] = previous
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_type"], "BillValidationError")


if __name__ == "__main__":
    unittest.main()
