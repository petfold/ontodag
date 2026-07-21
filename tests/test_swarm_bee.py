"""Live Bee integration test for the `odag` CLI Swarm backend.

Skips automatically unless BEE_API **and** BEE_BATCH are set — mirroring the
gating of `test_recordstore_bee.py` in the recordstore repo. Unlike
`test_cli.py` (which drives an in-memory RecordStore double), this exercises
the *real* SwarmBackend — BeeBytesStore + FilePointer over a live node —
end-to-end through `dispatch()`, exactly as the `odag` command does.

Run it against a live node (see CLAUDE.md "Bee integration status" for the
caveats — always pass a real BEE_BATCH so nothing auto-buys):

    BEE_API=http://localhost:1633 BEE_BATCH=<batchID> \
        python3 -m pytest tests/test_swarm_bee.py -v

A validated reference run (bee v2.8.1 light node, Gnosis mainnet, 2026-07-21)
is recorded in CLAUDE.md.
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

import ontodag.__main__ as cli

BEE_API = os.environ.get("BEE_API")
BEE_BATCH = os.environ.get("BEE_BATCH")


def _run(argv, session):
    """Dispatch a command like the CLI; return (exit_code, stdout_text)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.dispatch(argv, session)
    return code, buf.getvalue()


@unittest.skipUnless(
    BEE_API and BEE_BATCH,
    "set BEE_API and BEE_BATCH to run the live Bee integration test",
)
class TestSwarmBackendOnLiveBee(unittest.TestCase):
    def setUp(self):
        # A temp home isolates the FilePointer(s); BEE_API/BEE_BATCH come from
        # the environment, exactly as a real `odag` run reads them.
        self._home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("ONTODAG_HOME")
        os.environ["ONTODAG_HOME"] = self._home.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("ONTODAG_HOME", None)
        else:
            os.environ["ONTODAG_HOME"] = self._old_home
        self._home.cleanup()

    def _session(self, name="pets"):
        # A fresh Session re-hydrates from the FilePointer's current root,
        # reading records back from Bee — like a separate `odag` invocation.
        return cli.Session(f"swarm:{name}")

    def _root(self, name="pets"):
        with open(cli.SwarmBackend(name).pointer_path()) as fh:
            return fh.read().strip()

    def test_roundtrip_rehydrate_canonical_idempotent_removal(self):
        # Build a 5-node DAG; each put commits to Swarm.
        s = self._session()
        for argv in (
            ["put", "Animal"],
            ["put", "Pet"],
            ["put", "Dog", "Animal", "Pet"],
            ["put", "Cat", "Animal", "Pet"],
            ["put", "Spaniel", "Dog"],
        ):
            self.assertEqual(_run(argv, s)[0], 0, f"put failed: {argv}")

        # Query from a brand-new session -> must hydrate from Swarm.
        code, out = _run(["get", "Animal", "Pet"], self._session())
        self.assertEqual((code, out), (0, "Cat\nDog\nSpaniel\n"))

        root = self._root()
        self.assertTrue(root, "commit produced no root ref")

        # Canonical / history-independent root: rebuild the same graph under a
        # different store name AND a different insertion order -> same root.
        s2 = self._session("pets2")
        for argv in (
            ["put", "Pet"],
            ["put", "Animal"],
            ["put", "Cat", "Pet", "Animal"],
            ["put", "Dog", "Pet", "Animal"],
            ["put", "Spaniel", "Dog"],
        ):
            self.assertEqual(_run(argv, s2)[0], 0, f"put failed: {argv}")
        self.assertEqual(self._root("pets2"), root,
                         "same graph content must yield the same root ref")

        # Idempotent commit: re-put an existing edge -> root unchanged.
        _run(["put", "Spaniel", "Dog"], self._session())
        self.assertEqual(self._root(), root, "no-op commit changed the root")

        # Removal persists to Swarm.
        self.assertEqual(_run(["remove", "Cat"], self._session())[0], 0)
        code, out = _run(["get", "Animal", "Pet"], self._session())
        self.assertEqual((code, out), (0, "Dog\nSpaniel\n"))
        self.assertNotEqual(self._root(), root, "removal did not move the root")


if __name__ == "__main__":
    unittest.main()
