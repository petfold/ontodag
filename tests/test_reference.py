"""docs/REFERENCE.md is pinned to the code.

The reference's promise is that its tables and the code never disagree —
the lesson of TestTheBoundaryIsAlsoDeclared generalized to documentation:
a claim asserted only in prose is a claim nothing defends. Each test here
derives the ground truth from the code (or metadata) and asserts the
reference names it. Deliberately name-level, not prose-level: wording may
change freely; a missing or phantom name must fail.
"""

import os
import re
import unittest

import ontodag
from ontodag import dimensions as dims
from ontodag.__main__ import _SETTINGS
from ontodag.prelude import DECLARATIONS, PRELUDE_VERSION
from ontodag.surface import SURFACE_VERSION

REFERENCE = os.path.join(os.path.dirname(__file__), "..", "docs",
                         "REFERENCE.md")


def reference_text():
    with open(REFERENCE) as fh:
        return fh.read()


class TestReferenceIsPinned(unittest.TestCase):
    def setUp(self):
        self.text = reference_text()

    def test_versions(self):
        self.assertIn(f"contract `{ontodag.CONTRACT_VERSION}`", self.text)
        self.assertIn(f"registry `{dims.REGISTRY_VERSION}`", self.text)
        self.assertIn(f"prelude `{PRELUDE_VERSION}`", self.text)
        self.assertIn(f"surface `{SURFACE_VERSION}`", self.text)

    def test_every_cli_command_is_listed(self):
        from ontodag import __main__ as cli
        source = open(cli.__file__).read()
        commands = set(re.findall(r'add_parser\("([a-z]+)"', source))
        self.assertGreater(len(commands), 10)   # the extraction worked
        for command in commands:
            self.assertRegex(self.text, rf"`{command}[ `]",
                             f"CLI command {command!r} missing from "
                             f"REFERENCE.md §4")

    def test_every_setting_is_listed_with_its_env(self):
        for key, spec in _SETTINGS.items():
            self.assertIn(f"`{key}`", self.text,
                          f"setting {key!r} missing from REFERENCE.md")
            self.assertIn(f"`{spec.env}`", self.text,
                          f"env var {spec.env!r} missing from REFERENCE.md")

    def test_every_kind_is_listed(self):
        for kind in dims.KINDS:
            self.assertIn(f"`{kind}`", self.text,
                          f"kind {kind!r} missing from REFERENCE.md §6")

    def test_every_mcp_tool_is_listed(self):
        from ontodag import mcp
        source = open(mcp.__file__).read()
        tools = set(re.findall(r'\{"name": "([a-z_]+)"', source))
        self.assertGreater(len(tools), 8)
        for tool in tools:
            self.assertIn(f"`{tool}`", self.text,
                          f"MCP tool {tool!r} missing from REFERENCE.md §8")

    def test_every_extra_is_listed(self):
        import tomllib
        pyproject = os.path.join(os.path.dirname(REFERENCE), "..",
                                 "pyproject.toml")
        with open(pyproject, "rb") as fh:
            extras = tomllib.load(fh)["project"]["optional-dependencies"]
        for extra in extras:
            self.assertIn(f"`{extra}`", self.text,
                          f"extra {extra!r} missing from REFERENCE.md §2")

    def test_every_pack_is_listed(self):
        from ontodag.packs import PACKS
        for pack in PACKS:
            self.assertIn(f"`{pack}`", self.text,
                          f"pack {pack!r} missing from REFERENCE.md")

    def test_every_prelude_head_is_listed(self):
        for name, parents in DECLARATIONS:
            if parents and parents[0].endswith("-dimension"):
                self.assertIn(f"`{name}`", self.text,
                              f"prelude head {name!r} missing from "
                              f"REFERENCE.md §6")

    def test_every_public_ontodag_method_is_listed(self):
        from ontodag.dag import OntoDAG
        for method in (m for m in dir(OntoDAG) if not m.startswith("_")):
            if method == "deepcopy":
                continue    # an Item-copy helper, not graph API
            self.assertIn(f"`{method}", self.text,
                          f"OntoDAG method {method!r} missing from "
                          f"REFERENCE.md §5")

    def test_plans_are_marked_unshipped(self):
        # The reference must keep sending readers to plans/ with the
        # right expectation — drafts, not features.
        self.assertIn("plans/", self.text)
        self.assertIn("nothing in there is shipped", self.text.lower())


if __name__ == "__main__":
    unittest.main()
