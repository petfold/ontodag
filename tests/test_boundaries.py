"""Dependency-boundary tests.

The architecture rests on two one-directional boundaries (see CLAUDE.md and
docs/SWARM_DESIGN.md §2):

  B1  The core `ontodag` package must be importable and fully functional
      with no Swarm, no recordstore, and no optional dependency installed
      (owlready2, graphviz, dot2tex, flask). The Swarm layer is an optional
      persistence backend, not part of the data structure.
  B2  `recordstore` must never depend on OntoDAG — it is a generic record
      store with no graph semantics — and it stays stdlib-only.

Import checks run in a fresh subprocess so results are not polluted by
whatever this test process has already imported.
"""

import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")

# Top-level module names the core must not pull in at import time.
CORE_FORBIDDEN = ("recordstore", "owlready2", "graphviz", "dot2tex", "flask")


def fresh_import(module, forbidden):
    """Import `module` in a clean interpreter; return forbidden modules loaded."""
    code = (
        "import sys\n"
        f"import {module}\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {forbidden!r})\n"
        "sys.stdout.write(','.join(bad))\n"
    )
    env = dict(os.environ, PYTHONPATH=SRC)
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    if proc.returncode != 0:
        raise AssertionError(f"importing {module} failed:\n{proc.stderr}")
    return [m for m in proc.stdout.split(",") if m]


class TestCoreIsSwarmFree(unittest.TestCase):
    def test_import_ontodag_pulls_no_swarm_or_optional_deps(self):
        loaded = fresh_import("ontodag", CORE_FORBIDDEN)
        self.assertEqual(
            loaded, [],
            f"importing the core ontodag package loaded {loaded}; the core "
            "must work with no Swarm layer and no optional dependency",
        )

    def test_core_is_functional_without_swarm(self):
        # Build and query a small DAG in an interpreter that has never seen
        # recordstore or any optional dependency.
        code = (
            "from ontodag import OntoDAG, Item\n"
            "d = OntoDAG()\n"
            "a, b, x = Item('A'), Item('B'), Item('X')\n"
            "d.put(a, [])\n"
            "d.put(b, [])\n"
            "d.put(x, [a, b])\n"
            "names = sorted(i.name for i in d.get([a, b]))\n"
            "assert names == ['X'], names\n"
        )
        env = dict(os.environ, PYTHONPATH=SRC)
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestRecordstoreIsOntodagFree(unittest.TestCase):
    def test_import_recordstore_pulls_no_ontodag(self):
        loaded = fresh_import("recordstore", ("ontodag",))
        self.assertEqual(loaded, [], f"recordstore imported {loaded}")

    def test_recordstore_source_is_stdlib_only(self):
        # The dependency direction is ontodag -> recordstore, never the
        # reverse. Module-level imports must be stdlib-only; third-party
        # imports are allowed only lazily inside functions (BeeChunkStore
        # imports `requests` this way), and ontodag is banned everywhere.
        import ast

        def imported_tops(node):
            if isinstance(node, ast.Import):
                return [a.name.split(".")[0] for a in node.names]
            if isinstance(node, ast.ImportFrom) and not node.level:
                return [node.module.split(".")[0]]
            return []                        # relative import or not an import

        pkg_dir = os.path.join(SRC, "recordstore")
        for fname in sorted(os.listdir(pkg_dir)):
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(pkg_dir, fname)) as f:
                tree = ast.parse(f.read(), filename=fname)
            for node in ast.walk(tree):      # anywhere: never ontodag
                for top in imported_tops(node):
                    self.assertNotEqual(top, "ontodag",
                                        f"{fname} imports ontodag")
            for node in tree.body:           # module level: stdlib only
                for top in imported_tops(node):
                    self.assertIn(
                        top, sys.stdlib_module_names,
                        f"{fname} imports non-stdlib module {top!r} at module "
                        "level; third-party imports must stay lazy",
                    )


if __name__ == "__main__":
    unittest.main()
