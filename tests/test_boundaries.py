"""Dependency-boundary tests.

The architecture rests on two one-directional boundaries (see CLAUDE.md and
docs/SWARM_DESIGN.md §2):

  B1  The core `ontodag` package must be importable and fully functional
      with no Swarm, no recordstore, and no optional dependency installed
      (owlready2, graphviz, dot2tex, flask). The Swarm layer is an optional
      persistence backend, not part of the data structure.
  B2  `recordstore` must never depend on OntoDAG — it is a generic record
      store with no graph semantics — and it stays stdlib-only. Since its
      extraction to github.com/petfold/recordstore (July 2026) it is an
      installed dependency, so these checks run against the installed
      package rather than an in-repo source tree.

Import checks run in a fresh subprocess so results are not polluted by
whatever this test process has already imported.
"""

import os
import subprocess
import sys
import unittest
from unittest import mock

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


    def test_lazy_needs_no_recordstore(self):
        # The on-demand reader duck-types its store like eager does,
        # so importing it must not drag recordstore (or requests) in either.
        loaded = fresh_import("ontodag.lazy", CORE_FORBIDDEN)
        self.assertEqual(
            loaded, [],
            f"importing ontodag.lazy loaded {loaded}; it must stay "
            "duck-typed over the record store",
        )

    def test_mcp_module_imports_stay_core_only(self):
        # The agent surface (ontodag.mcp) is stdlib + core at module level;
        # recordstore loads lazily inside functions, exactly like the CLI's
        # swarm path. (recordstore is an installed dependency — this checks
        # coupling, not availability.)
        loaded = fresh_import("ontodag.mcp", CORE_FORBIDDEN)
        self.assertEqual(
            loaded, [],
            f"importing ontodag.mcp loaded {loaded}; the record store must "
            "stay a lazy, function-local import",
        )

    def test_certificates_module_imports_stay_core_only(self):
        # Certificates compose recordstore proofs, but only at call time:
        # module-level imports stay core-only, like mcp and the CLI's
        # swarm path.
        loaded = fresh_import("ontodag.certificates", CORE_FORBIDDEN)
        self.assertEqual(
            loaded, [],
            f"importing ontodag.certificates loaded {loaded}; recordstore "
            "must stay a lazy, function-local import",
        )

    def test_provenance_module_imports_stay_core_only(self):
        # Records are signed and stored, but both dependencies load lazily:
        # recordstore for canonical bytes and the store, `bee` for real
        # secp256k1 signing (the same package the feed pointer uses).
        loaded = fresh_import("ontodag.provenance",
                              CORE_FORBIDDEN + ("bee",))
        self.assertEqual(
            loaded, [],
            f"importing ontodag.provenance loaded {loaded}; recordstore "
            "and bee must stay lazy, function-local imports",
        )

    def test_packs_module_imports_stay_core_only(self):
        loaded = fresh_import("ontodag.packs", CORE_FORBIDDEN)
        self.assertEqual(loaded, [],
                         f"importing ontodag.packs loaded {loaded}")

    def test_migrate_module_imports_stay_core_only(self):
        loaded = fresh_import("ontodag.migrate", CORE_FORBIDDEN)
        self.assertEqual(loaded, [],
                         f"importing ontodag.migrate loaded {loaded}")

    def test_core_never_imports_the_surface(self):
        # SURFACE_LAYER.md §7: ontodag.surface is opt-in by import — the
        # human-facing rendering layer. The core must never call it, or
        # canonical data paths would grow a display dependency.
        code = (
            "import sys\n"
            "import ontodag\n"
            "assert 'ontodag.surface' not in sys.modules, "
            "'the core imported ontodag.surface'\n"
        )
        env = dict(os.environ, PYTHONPATH=SRC)
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            env=env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestRecordstoreIsOntodagFree(unittest.TestCase):
    def test_import_recordstore_pulls_no_ontodag(self):
        loaded = fresh_import("recordstore", ("ontodag",))
        self.assertEqual(loaded, [], f"recordstore imported {loaded}")

    def test_recordstore_source_is_stdlib_only(self):
        # The dependency direction is ontodag -> recordstore, never the
        # reverse. Module-level imports must be stdlib-only; third-party
        # imports are allowed only lazily inside functions (BeeBytesStore
        # imports `requests` this way), and ontodag is banned everywhere.
        import ast

        def imported_tops(node):
            if isinstance(node, ast.Import):
                return [a.name.split(".")[0] for a in node.names]
            if isinstance(node, ast.ImportFrom) and not node.level:
                return [node.module.split(".")[0]]
            return []                        # relative import or not an import

        import importlib.util
        spec = importlib.util.find_spec("recordstore")
        self.assertIsNotNone(spec, "recordstore is not installed")
        pkg_dir = spec.submodule_search_locations[0]
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


class TestTheBoundaryIsAlsoDeclared(unittest.TestCase):
    """B1 in the packaging metadata, not just in the import graph.

    B1 above proves the core *imports* without optional dependencies. It
    cannot prove the core does not *require* them, because in any dev
    environment they are installed and nothing fails. Until 2026-08-02 that
    gap was real: `pyproject.toml` declared graphviz and owlready2 as hard
    dependencies, so `pip install ontodag` fetched 31 MB, a compiled
    extension and two bundled Java reasoners to deliver a 648 KB package
    that used none of them — and, because owlready2 ships sdist-only, it
    also demanded a C toolchain and made the package uninstallable under
    Pyodide, where micropip cannot build sdists.

    A boundary asserted in code but not in metadata is not a boundary.
    """

    @staticmethod
    def _pyproject():
        import tomllib
        path = os.path.join(os.path.dirname(__file__), "..", "pyproject.toml")
        with open(path, "rb") as fh:
            return tomllib.load(fh)

    def test_the_base_install_has_no_third_party_dependency(self):
        declared = self._pyproject()["project"]["dependencies"]
        self.assertEqual(
            declared, [],
            "the base install must stay dependency-free: anything genuinely "
            "needed by the core belongs in the core, and everything else "
            "belongs in an extra. Adding a hard dependency here silently "
            "revokes B1 for every installed user.",
        )

    def test_every_optional_dependency_lives_in_an_extra(self):
        extras = self._pyproject()["project"]["optional-dependencies"]
        for package, extra in (("graphviz", "viz"), ("owlready2", "owl"),
                               ("recordstore", "store")):
            declared = " ".join(extras.get(extra, []))
            self.assertIn(package, declared,
                          f"{package} should be reachable via [{extra}]")

    def test_a_missing_extra_teaches_instead_of_traceback(self):
        # The failure a user actually meets. A ModuleNotFoundError names a
        # package; what they need is the pip command, and for rendering they
        # also need to know a system binary is involved.
        import ontodag
        from ontodag import viz
        for get, wanted in (
            (lambda: viz._digraph(), "ontodag[viz]"),
            (lambda: ontodag.OWLOntology, "ontodag[owl]"),
        ):
            with mock.patch.dict(sys.modules,
                                 {"graphviz": None, "ontodag.owl": None}):
                try:
                    get()
                except ImportError as exc:
                    self.assertIn(wanted, str(exc))
                else:
                    self.fail(f"expected an ImportError mentioning {wanted}")
