"""The standard prelude (ontodag.prelude, SURFACE_LAYER.md §9.2).

What must hold: adoption is an explicit, idempotent merge (never a default
of a fresh store); a typed value works immediately afterwards; and
"prelude v1" IS a specific canonical fingerprint — the golden root below
changes only when DECLARATIONS change, and any such change must bump
PRELUDE_VERSION (that is what the pin is for).
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from recordstore import MemoryBytesStore, RecordStore

import ontodag
from ontodag.__main__ import Session, dispatch
from ontodag.prelude import PRELUDE_VERSION, apply, prelude_dag

# The canonical fingerprint of prelude v2 — the "well-known root" the
# adoption story rests on: everyone merging this version contributes the
# byte-identical subgraph. If this test fails, either the prelude changed
# (bump PRELUDE_VERSION and re-pin, deliberately) or canonicalization
# regressed (fix that instead).
GOLDEN_ROOT_V2 = \
    "18e42105bd2d9a4a07dc69ad0097fc3fd7b4e1eac83487f8c399c0c22d0f77b6"


class TestPrelude(unittest.TestCase):
    def test_golden_root_pins_the_version(self):
        self.assertEqual(PRELUDE_VERSION, 2)
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        apply(dag)
        self.assertEqual(dag.commit(), GOLDEN_ROOT_V2)

    def test_typed_values_work_immediately_after_adoption(self):
        dag = prelude_dag()
        dag.put("parcel", ["weight(3kg)"])
        dag.put("trip", ["time(2026-08)"])
        dag.put("tyre", ["pressure(32psi)"])
        self.assertTrue(dag.is_below("parcel", "weight(..5kg)"))
        self.assertTrue(dag.is_below("trip", "time(2026)"))
        self.assertTrue(dag.is_below("tyre", "pressure(..3bar)"))
        self.assertTrue(dag.is_below("geo(u2ed)", "geo(u2)"))
        self.assertTrue(dag.is_below("size(19x23x39cm)",
                                     "size(20x30x40cm)"))

    def test_apply_is_idempotent_and_additive(self):
        dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
        dag.put("pet", [])                      # existing content survives
        dag.put("weight", [])                   # even a bare existing head
        apply(dag)
        first = dag.commit()
        apply(dag)
        self.assertEqual(dag.commit(), first)   # merge is idempotent
        self.assertIn("pet", dag.nodes)
        self.assertTrue(dag.is_below("weight", "linear-dimension"))


class TestPreludeCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.session = Session(os.path.join(self.tmp.name, "store.od"))

    def run_cmd(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = dispatch(argv, self.session)
        return code, buf.getvalue().splitlines()

    def test_prelude_then_typed_values_no_ceremony(self):
        code, lines = self.run_cmd(["prelude"])
        self.assertEqual((code, lines), (0, []))     # silent on success
        code, _ = self.run_cmd(["put", "parcel", "weight(3kg)"])
        self.assertEqual(code, 0)
        code, lines = self.run_cmd(["get", "weight(..5kg)"])
        self.assertEqual(code, 0)
        self.assertIn("parcel", lines)   # (the value node rides along too)
        self.assertEqual(self.run_cmd(["prelude"])[0], 0)   # idempotent

    def test_show_prints_without_merging(self):
        code, lines = self.run_cmd(["prelude", "--show"])
        self.assertEqual(code, 0)
        self.assertIn(f"# ontodag prelude v{PRELUDE_VERSION}", lines)
        self.assertIn("weight linear-dimension", lines)
        _, listed = self.run_cmd(["list"])
        self.assertEqual(listed, [])                 # nothing was merged


if __name__ == "__main__":
    unittest.main()
