"""The read-only page's Swarm layer (demo/freedom/swarm.js), run under node
against chunk trees made by swarmfs's splitter: addresses, trees from 0 to
600 KB, a tampered or missing chunk refused, one read per chunk. Without
swarmfs, make_vectors.py's splitter on pycryptodome (the `act` extra, so
CI) makes them, checked against swarmfs's where both are present. Skips
without node, or with neither splitter."""

import importlib.util
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(os.path.dirname(HERE), "demo", "freedom")


@unittest.skipUnless(shutil.which("node"), "needs node")
@unittest.skipUnless(importlib.util.find_spec("swarmfs") or importlib.util.find_spec("Crypto"),
                     "needs swarmfs or pycryptodome for the splitter")
class TestSwarmJs(unittest.TestCase):
    def test_swarm_js_joins_and_checks_chunk_trees(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            vectors = os.path.join(d, "vectors.json")
            with open(vectors, "w") as fh:
                subprocess.run([sys.executable, os.path.join(PAGE, "test", "make_vectors.py")],
                               check=True, stdout=fh)
            run = subprocess.run(["node", os.path.join(PAGE, "test", "test_swarm.mjs"), vectors],
                                 capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("FAIL", run.stdout)
        self.assertIn("tampered leaf refused", run.stdout)
