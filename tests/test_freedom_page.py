"""The page's Swarm layer, run under node. swarm.js against chunk trees
made by swarmfs's splitter: addresses, trees from 0 to 600 KB, a tampered
or missing chunk refused, one read per chunk. publish.js against swarmfs's
signer: a feed update signed byte for byte the same. savehelp.js: which
browser setting it offers where a page saves only by downloading. Without
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


@unittest.skipUnless(shutil.which("node"), "needs node")
class TestPublishJs(unittest.TestCase):
    """The page's writing half (demo/freedom/publish.js): a feed update
    signed in the page is byte for byte the one swarmfs signs (the vector in
    test/feed_vector.json), and blobs are addressed as the splitter does."""

    def run_node(self, *args):
        run = subprocess.run(["node", os.path.join(PAGE, "test", "test_publish.mjs"), *args],
                             capture_output=True, text=True, timeout=300)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertNotIn("FAIL", run.stdout)
        return run.stdout

    def test_a_feed_update_signed_in_the_page_is_swarmfs_s(self):
        out = self.run_node(os.path.join(PAGE, "test", "feed_vector.json"))
        self.assertIn("byte for byte libsecp256k1's", out)

    @unittest.skipUnless(importlib.util.find_spec("swarmfs") or importlib.util.find_spec("Crypto"),
                         "needs swarmfs or pycryptodome for the splitter")
    def test_blobs_are_addressed_as_the_splitter_does(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            vectors = os.path.join(d, "vectors.json")
            with open(vectors, "w") as fh:
                subprocess.run([sys.executable, os.path.join(PAGE, "test", "make_vectors.py")],
                               check=True, stdout=fh)
            out = self.run_node(os.path.join(PAGE, "test", "feed_vector.json"), vectors)
        self.assertIn("address of a 600000-byte blob", out)

    @unittest.skipUnless(importlib.util.find_spec("coincurve") and importlib.util.find_spec("swarmfs"),
                         "needs swarmfs with coincurve to sign the vector again")
    def test_the_vector_is_what_swarmfs_signs(self):
        import json
        run = subprocess.run([sys.executable, os.path.join(PAGE, "test", "make_feed_vector.py")],
                             capture_output=True, text=True, check=True)
        with open(os.path.join(PAGE, "test", "feed_vector.json")) as fh:
            self.assertEqual(json.loads(run.stdout), json.load(fh))


@unittest.skipUnless(shutil.which("node"), "needs node")
class TestSaveHelpJs(unittest.TestCase):
    def test_the_help_fits_the_browser(self):
        run = subprocess.run(["node", os.path.join(PAGE, "test", "test_savehelp.mjs")],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("all passed", run.stdout)
