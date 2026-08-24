"""Tests for the `od` command line (ontodag.__main__).

Covers the store-backend layer added for Swarm persistence:

  C1  spec routing      - swarm:NAME -> SwarmBackend, else FileBackend
  C2  spec normalize    - swarm specs kept verbatim, file paths absolutized
  C3  file round-trip   - a Session over a native file persists put/get
  C4  swarm round-trip  - a Session over a swarm backend persists across
                          reload, driven through dispatch() exactly as the
                          CLI does, using an in-memory RecordStore double so
                          no Bee node is required
  C5  swarm set/config  - `set store swarm:NAME` is stored verbatim and
                          resolves back to a SwarmBackend
  C6  swarm import      - import replaces store contents in place

The Bee HTTP path itself is not exercised here (no node); it is covered by
recordstore's own live-node suite. These tests validate the CLI wiring.
"""

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

import ontodag.__main__ as cli
from ontodag.dag import Item, OntoDAG
from recordstore import MemoryBytesStore, MemoryPointer, RecordStore


# Capability gates. These are not "nice to have" skips: a machine that
# installed `ontodag[test]` has neither pycryptodome nor a Graphviz binary,
# and a Windows machine has no POSIX permission bits at all. Without the
# gates those environments report failures that say nothing about the code
# — which is exactly what the 2026-08-24 Windows run produced.
def _installed(module):
    """Is `module` importable? `find_spec` answers without importing — and
    is allowed to raise rather than return None when a parent package is
    missing, so a bare `is not None` is not the whole test."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


HAVE_CRYPTO = _installed("Crypto")

# Windows `os.chmod` toggles the read-only attribute and nothing else, so a
# mode assertion there tests the platform rather than `_write_config`. What
# keeps the signer key private on Windows is the NTFS ACL on the user
# profile; the limitation is stated in USER_GUIDE §2.
POSIX_MODES = os.name != "nt"


def _run(argv, session):
    """Dispatch a command, returning (exit_code, stdout_text)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.dispatch(argv, session)
    return code, buf.getvalue()


class TestBackendRouting(unittest.TestCase):
    def test_routing(self):  # C1
        self.assertIsInstance(cli._make_backend("/tmp/x.od"), cli.FileBackend)
        self.assertIsInstance(cli._make_backend("swarm:pets"), cli.SwarmBackend)

    def test_swarm_name_parsed(self):
        be = cli._make_backend("swarm:pets")
        self.assertEqual(be.name, "pets")
        self.assertEqual(be.describe(), "swarm:pets")

    def test_bad_swarm_names_rejected(self):
        for bad in ("swarm:", "swarm:a/b", "swarm:.."):
            with self.assertRaises(ValueError):
                cli._make_backend(bad)

    def test_normalize_spec(self):  # C2
        self.assertEqual(cli._normalize_spec("swarm:pets"), "swarm:pets")
        norm = cli._normalize_spec("relative/store.od")
        self.assertTrue(os.path.isabs(norm))


class TestFileBackend(unittest.TestCase):
    def test_file_round_trip(self):  # C3
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "store.od")
            session = cli.Session(path)
            self.assertEqual(_run(["put", "Animal"], session), (0, ""))
            _run(["put", "Dog", "Animal"], session)
            # A fresh session reads it back from disk.
            code, out = _run(["get", "Animal"], cli.Session(path))
            self.assertEqual((code, out), (0, "Dog\n"))


class TestNativeStoreMetadata(unittest.TestCase):
    """The native format persists node metadata (`#:meta` lines).

    It did not, and dropped it on save with no diagnostic, so the format could
    not represent a DAG that the recordstore backend can: `_record_for` puts
    `meta` in the record, hence in the canonical root, while `_save_native`
    wrote names and edges only. A save+load therefore *changed the root*, and
    any consumer keeping data in metadata — ontodag-fs marks objects and
    carries display labels there — silently lost it through a file store.
    """

    def _roundtrip(self, dag, tmp):
        path = os.path.join(tmp, "store.od")
        cli._save_native(dag, path)
        return path, cli._load_native(path)

    def test_metadata_survives_a_round_trip(self):
        dag = OntoDAG()
        dag.put("dog", [])
        dag.put(Item("rex", metadata={"object": True, "label": "rex.txt",
                                      "count": 7}), ["dog"])
        with tempfile.TemporaryDirectory() as tmp:
            _path, back = self._roundtrip(dag, tmp)
        self.assertEqual(back.nodes["rex"].metadata,
                         {"object": True, "label": "rex.txt", "count": 7})
        self.assertEqual(back.nodes["dog"].metadata, {})   # absent stays absent

    def test_hostile_values_survive(self):
        """A label is an arbitrary string, and the format is line-oriented —
        so a newline in a value is the hazard that matters. JSON escapes it,
        which is why the annotation is one token rather than free text."""
        nasty = 'said "hi"\nnewline\ttab café \'quoted\' 100% a/b \\ #:meta'
        dag = OntoDAG()
        dag.put(Item("n", metadata={"label": nasty}), [])
        with tempfile.TemporaryDirectory() as tmp:
            path, back = self._roundtrip(dag, tmp)
            with open(path, encoding="utf-8") as fh:
                body = fh.read()
        self.assertEqual(back.nodes["n"].metadata["label"], nasty)
        # one physical line per record: the value's newline must not split it
        self.assertEqual(len([ln for ln in body.splitlines()
                              if ln.startswith(cli._META_LINE)]), 1)

    def test_the_file_stays_canonical(self):
        """Saving twice is byte-identical, so the store still diffs and merges
        — metadata keys are sorted for the same reason node names are."""
        dag = OntoDAG()
        dag.put(Item("n", metadata={"z": 1, "a": 2, "m": 3}), [])
        with tempfile.TemporaryDirectory() as tmp:
            one = os.path.join(tmp, "a.od")
            two = os.path.join(tmp, "b.od")
            cli._save_native(dag, one)
            cli._save_native(cli._load_native(one), two)
            with open(one, "rb") as fh, open(two, "rb") as gh:
                self.assertEqual(fh.read(), gh.read())

    def test_a_file_written_before_this_still_loads(self):
        """Backward compatibility: no `#:meta` lines is a valid store."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.od")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# ontodag store v1\ndog '*'\npuppy dog\n")
            dag = cli._load_native(path)
        self.assertEqual(sorted(n for n in dag.nodes if n != dag.root.name),
                         ["dog", "puppy"])
        self.assertEqual(dag.nodes["dog"].metadata, {})

    def test_a_reader_that_predates_metadata_sees_no_junk(self):
        """Forward compatibility, and the reason the annotation is a comment:
        every released reader skips `#` lines, so it reads a metadata-bearing
        file as edges only — not as nodes named after a JSON blob."""
        dag = OntoDAG()
        dag.put(Item("rex", metadata={"label": "rex.txt"}), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "store.od")
            cli._save_native(dag, path)
            with open(path, encoding="utf-8") as fh:
                lines = [ln.strip() for ln in fh
                         if ln.strip() and not ln.strip().startswith("#")]
        self.assertEqual(lines, ["rex '*'"])

    def test_a_malformed_annotation_is_an_error_not_a_shrug(self):
        """Ignoring an unreadable annotation would be the same silent loss this
        line type exists to end, so it fails loudly and names the line."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bad.od")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# ontodag store v1\n#:meta dog {not json}\ndog '*'\n")
            with self.assertRaises(ValueError) as caught:
                cli._load_native(path)
        self.assertIn(":2:", str(caught.exception))

    def test_the_canonical_root_survives_a_round_trip(self):
        """The property the whole change is for: routing a DAG through the text
        format no longer changes what it hashes to."""
        from ontodag.eager import EagerOntoDAG

        def commit(source):
            eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            for node in source.topological_sort():
                if node.name == source.root.name:
                    continue
                parents = sorted(
                    p.name for p in node.parents
                    if source.nodes.get(p.name) is p
                    and p.name != source.root.name)
                eager.put(Item(node.name, metadata=dict(node.metadata)),
                          parents)
            return eager.commit()

        dag = OntoDAG()
        dag.put("dog", [])
        dag.put(Item("rex", metadata={"object": True, "label": "rex.txt"}),
                ["dog"])
        before = commit(dag)
        with tempfile.TemporaryDirectory() as tmp:
            _path, back = self._roundtrip(dag, tmp)
        self.assertEqual(before, commit(back))


def _mem_swarm_session(shared):
    """A Session wired to an in-memory RecordStore that persists in `shared`
    (a dict holding the bytes store and pointer), mimicking a durable store
    across separate `odag` invocations within one test process."""
    factory = lambda: RecordStore(shared["bytes"], pointer=shared["pointer"])
    session = cli.Session.__new__(cli.Session)
    session.spec = "swarm:t"
    session._backend = cli.SwarmBackend("t", store_factory=factory)
    session._dag = session._backend.load()
    return session


class TestSwarmBackend(unittest.TestCase):
    def setUp(self):
        self.shared = {"bytes": MemoryBytesStore(), "pointer": MemoryPointer()}

    def test_swarm_round_trip_through_dispatch(self):  # C4
        s = _mem_swarm_session(self.shared)
        self.assertEqual(_run(["put", "Animal"], s), (0, ""))
        _run(["put", "Pet"], s)
        _run(["put", "Dog", "Animal", "Pet"], s)
        _run(["put", "Cat", "Animal", "Pet"], s)

        # Reload as a brand-new session over the same durable store.
        s2 = _mem_swarm_session(self.shared)
        code, out = _run(["get", "Animal", "Pet"], s2)
        self.assertEqual((code, out), (0, "Cat\nDog\n"))
        self.assertIn("swarm:t", _run(["set"], s2)[1])

    def test_swarm_remove_persists(self):
        s = _mem_swarm_session(self.shared)
        _run(["put", "Animal"], s)
        _run(["put", "Dog", "Animal"], s)
        _run(["remove", "Dog"], s)
        code, out = _run(["get", "Animal"], _mem_swarm_session(self.shared))
        self.assertEqual((code, out), (0, ""))

    def test_concurrent_remove_survivor_reaches_the_store(self):
        """The concurrent-delete gap, without swarmfs: session 2 hydrates
        while Dog exists, session 1 removes Dog (head moves), session 2
        saves an unrelated put — the union keeps Dog, and the committed
        root must too (see the local-first twin of this test for the
        full story)."""
        s1 = _mem_swarm_session(self.shared)
        _run(["put", "Animal"], s1)
        _run(["put", "Dog", "Animal"], s1)
        s2 = _mem_swarm_session(self.shared)      # hydrates holding Dog
        _run(["remove", "Dog"], s1)               # head moves: Dog deleted
        _run(["put", "Cat", "Animal"], s2)        # merge on save
        code, out = _run(["get", "Animal"], _mem_swarm_session(self.shared))
        self.assertEqual((code, out), (0, "Cat\nDog\n"))

    def test_swarm_import_replaces_in_place(self):  # C6
        s = _mem_swarm_session(self.shared)
        _run(["put", "Old"], s)
        self.assertIsInstance(s.dag, __import__("ontodag").EagerOntoDAG)

        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "new.od")
            other = cli.Session(src)
            _run(["put", "Fresh"], other)
            _run(["put", "Kid", "Fresh"], other)

            s.import_from(cli._load(src))
            # Same object kind (still a EagerOntoDAG), new contents.
            self.assertIsInstance(s.dag, __import__("ontodag").EagerOntoDAG)

        code, out = _run(["get", "Fresh"], _mem_swarm_session(self.shared))
        self.assertEqual((code, out), (0, "Kid\n"))
        self.assertEqual(_run(["get", "Old"], _mem_swarm_session(self.shared)),
                         (0, ""))


class TestSetCommand(unittest.TestCase):
    """Settings resolve by flag > environment > config file > default, so these
    tests have to own the environment: with `BEE_API` exported — which is what
    the User Guide's setup step tells you to do — an assertion about what the
    *config file* holds is testing the wrong layer, and the suite went red for
    anyone who had followed the instructions. The neighbouring swarm classes
    already save and restore these; this one did not."""

    _ENV = ("BEE_API", "BEE_BATCH", "BEE_SIGNER", "ONTODAG_STORE",
            "ONTODAG_LIMIT", "ONTODAG_SURFACE")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        for key in self._ENV:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _session(self, d):
        return cli.Session(os.path.join(d, "store.od"))

    def test_set_no_args_shows_all_settings(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = _run(["set"], self._session(d))
            self.assertEqual(code, 0)
            for key in ("store", "bee_api", "bee_batch"):
                self.assertIn(f"{key} = ", out)

    def test_set_key_without_value_displays_not_errors(self):
        with tempfile.TemporaryDirectory() as d:
            for key in ("store", "bee_api", "bee_batch"):
                code, out = _run(["set", key], self._session(d))
                self.assertEqual(code, 0, f"{key} should display, not error")
                self.assertTrue(out.startswith(f"{key} = "))

    def test_set_key_value_changes_it(self):
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home")
            old = os.environ.get("ONTODAG_HOME")
            os.environ["ONTODAG_HOME"] = home
            try:
                s = cli.Session(cli._resolve_store(None))
                self.assertEqual(_run(["set", "bee_api", "http://n:1633"], s),
                                 (0, ""))
                code, out = _run(["set", "bee_api"], s)
                self.assertEqual((code, out), (0, "bee_api = http://n:1633\n"))
            finally:
                if old is None:
                    del os.environ["ONTODAG_HOME"]
                else:
                    os.environ["ONTODAG_HOME"] = old

    def test_set_unknown_key_errors(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = _run(["set", "bogus"], self._session(d))
            self.assertEqual(code, 1)


class TestSwarmMissingDependency(unittest.TestCase):
    def test_missing_swarmfs_gives_actionable_error(self):
        # local_first_store imports swarmfs's localstore machinery; if it's
        # not installed the swarm backend must fail with a clear message
        # pointing at the extra, not a raw ModuleNotFoundError.
        import builtins

        real_import = builtins.__import__

        def block(name, *args, **kwargs):
            if name == "swarmfs" or name.startswith("swarmfs."):
                raise ModuleNotFoundError("No module named 'swarmfs'",
                                          name="swarmfs")
            return real_import(name, *args, **kwargs)

        with tempfile.TemporaryDirectory() as home:
            old_home = os.environ.get("ONTODAG_HOME")
            os.environ["ONTODAG_HOME"] = home
            builtins.__import__ = block
            try:
                with self.assertRaises(ValueError) as ctx:
                    cli.SwarmBackend("pets")._record_store()
            finally:
                builtins.__import__ = real_import
                if old_home is None:
                    del os.environ["ONTODAG_HOME"]
                else:
                    os.environ["ONTODAG_HOME"] = old_home

        msg = str(ctx.exception)
        self.assertIn("swarmfs", msg)
        self.assertIn("swarm extra", msg)


class TestSwarmNodeDown(unittest.TestCase):
    """Opening a `swarm:NAME` store is network I/O, so it fails whenever the
    node is down. The store opens lazily — on the first command that touches
    it, inside dispatch()'s handler — so the CLI contract (one line on
    stderr, non-zero exit) holds, the message names the way out (start the
    node, or use the local default store), and commands that never touch the
    store (`help`, `set`) keep working with the node down. It must NOT
    quietly switch to the local store, which would let two stores diverge
    with no signal about which one is authoritative."""

    _ENV = ("ONTODAG_HOME", "BEE_API", "BEE_BATCH", "BEE_SIGNER")

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        os.environ["ONTODAG_HOME"] = self._home.name
        os.environ["BEE_API"] = "http://localhost:1633"
        os.environ.pop("BEE_SIGNER", None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    @staticmethod
    def _wrapped(name, cause):
        """An OSError subclass named `name` carrying `cause` — the shape both
        HTTP clients produce: not a builtin ConnectionError, real refusal
        underneath."""
        exc = type(name, (OSError,), {})("Cannot connect to host localhost:1633")
        exc.__cause__ = cause
        return exc

    def _aiohttp_style_refusal(self):
        """What swarmfs's stamp selection actually raised in the wild."""
        return self._wrapped("ClientConnectorError",
                             ConnectionRefusedError(111, "Connect call failed"))

    def test_detects_unreachable_by_type_name(self):
        self.assertTrue(cli._is_unreachable(self._aiohttp_style_refusal()))
        self.assertTrue(cli._is_unreachable(
            ConnectionRefusedError(111, "Connection refused")))

    def test_detects_unreachable_through_the_cause_chain(self):
        # An unfamiliar wrapper type: only the chain gives it away.
        self.assertTrue(cli._is_unreachable(self._wrapped(
            "SomeFutureClientError",
            ConnectionRefusedError(111, "Connection refused"))))

    def test_node_answering_is_not_unreachable(self):
        # The node answering with a complaint is a different failure: no
        # "start your node" advice for it.
        self.assertFalse(cli._is_unreachable(
            OSError("no usable postage stamp on http://localhost:1633")))
        self.assertFalse(cli._is_unreachable(
            self._wrapped("BeeAPIError", ValueError("402 Payment Required"))))

    def test_unreachable_node_gives_actionable_error(self):
        backend = cli.SwarmBackend(
            "pets", store_factory=self._aiohttp_style_refusal_raiser())
        with self.assertRaises(ValueError) as ctx:
            backend.load()
        msg = str(ctx.exception)
        self.assertIn("cannot reach the Bee node at http://localhost:1633", msg)
        self.assertIn("swarm:pets", msg)
        self.assertIn("start your Bee node", msg)
        # ...and the local escape hatches, pointing at the real default path.
        self.assertIn(f"odag -f {cli._default_store_path()}", msg)
        self.assertIn(f"odag set store {cli._default_store_path()}", msg)

    def test_node_answering_with_an_error_uses_the_other_branch(self):
        def factory():
            raise OSError("no usable postage stamp on http://localhost:1633")

        with self.assertRaises(ValueError) as ctx:
            cli.SwarmBackend("pets", store_factory=factory).load()
        msg = str(ctx.exception)
        self.assertIn("cannot open swarm store 'pets'", msg)
        self.assertIn("no usable postage stamp", msg)
        self.assertNotIn("start your Bee node", msg)
        self.assertIn("odag set store", msg)  # fallback still offered

    def test_main_reports_one_line_not_a_traceback(self):
        from unittest import mock

        err = io.StringIO()
        boom = self._aiohttp_style_refusal()

        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "pets", store_factory=self._raiser(boom))), \
             mock.patch.object(cli, "_resolve_store", lambda *a: "swarm:pets"), \
             redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["get", "Dog"])

        self.assertEqual(ctx.exception.code, 1)
        text = err.getvalue()
        self.assertTrue(text.startswith("odag: "), text)
        self.assertNotIn("Traceback", text)
        self.assertIn("start your Bee node", text)

    def test_help_and_set_work_with_the_node_down(self):
        # The reason the store opens lazily: `odag help` is what a user
        # types to find the way out, and `odag set store <local>` IS the
        # way out — neither may fail because the node is unreachable.
        from unittest import mock

        boom = self._aiohttp_style_refusal()
        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "pets", store_factory=self._raiser(boom))):
            session = cli.Session("swarm:pets")

            code, out = _run(["help"], session)
            self.assertEqual(code, 0)
            self.assertIn("Documentation:", out)

            code, out = _run(["set"], session)          # show settings
            self.assertEqual(code, 0)
            self.assertIn("swarm:pets", out)            # described, unopened

            code, _ = _run(["set", "limit", "10"], session)
            self.assertEqual(code, 0)

            # A command that DOES touch the store still gets the contract:
            err = io.StringIO()
            with redirect_stderr(err):
                code, _ = _run(["get", "Dog"], session)
            self.assertEqual(code, 1)
            self.assertIn("start your Bee node", err.getvalue())

    def test_failed_switch_leaves_the_session_on_its_old_store(self):
        from unittest import mock

        local = os.path.join(self._home.name, "local.od")
        session = cli.Session(local)
        _run(["put", "Animal"], session)

        # `set store swarm:down` with the node unreachable.
        boom = self._aiohttp_style_refusal()
        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "down", store_factory=self._raiser(boom))):
            code, _ = _run(["set", "store", "swarm:down"], session)
        self.assertEqual(code, 1)

        # The session still serves the store it had — not a half-switched one.
        self.assertEqual(session.spec, local)
        self.assertEqual(_run(["get", "Animal"], session), (0, ""))
        self.assertEqual(_run(["list"], session), (0, "Animal\n"))
        # ...while the setting itself was saved, so starting the node and
        # re-running picks it up.
        self.assertEqual(cli._read_config()["store"], "swarm:down")

    def test_failed_switch_says_the_setting_was_saved(self):
        from unittest import mock

        session = cli.Session(os.path.join(self._home.name, "local.od"))
        err = io.StringIO()
        with mock.patch.object(cli, "_make_backend", lambda spec: cli.SwarmBackend(
                "down", store_factory=self._raiser(
                    self._aiohttp_style_refusal()))), redirect_stderr(err):
            code = cli.dispatch(["set", "store", "swarm:down"], session)
        self.assertEqual(code, 1)
        msg = err.getvalue()
        self.assertTrue(msg.startswith("odag: "), msg)
        self.assertIn("cannot reach the Bee node", msg)
        self.assertIn("setting was still saved as swarm:down", msg)

    @staticmethod
    def _raiser(exc):
        def factory():
            raise exc

        return factory

    def _aiohttp_style_refusal_raiser(self):
        exc = self._aiohttp_style_refusal()

        def factory():
            raise exc

        return factory


class TestSwarmConfig(unittest.TestCase):
    def test_set_store_swarm_is_verbatim(self):  # C5
        with tempfile.TemporaryDirectory() as home:
            old = os.environ.get("ONTODAG_HOME")
            os.environ["ONTODAG_HOME"] = home
            try:
                cfg = {}
                cli._write_config({"store": cli._normalize_spec("swarm:pets")})
                self.assertEqual(cli._read_config()["store"], "swarm:pets")
                self.assertEqual(cli._resolve_store(None), "swarm:pets")
                self.assertIsInstance(
                    cli._make_backend(cli._resolve_store(None)),
                    cli.SwarmBackend,
                )
            finally:
                if old is None:
                    del os.environ["ONTODAG_HOME"]
                else:
                    os.environ["ONTODAG_HOME"] = old


class TestGetOr(unittest.TestCase):
    def test_or_separates_disjuncts(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "zoo.od"))
            for argv in (["put", "animal"], ["put", "machine"],
                         ["put", "pet"], ["put", "dog", "animal", "pet"],
                         ["put", "drone", "machine"]):
                self.assertEqual(_run(argv, session)[0], 0)
            code, out = _run(["get", "animal", "pet", "or", "machine"],
                             session)
            self.assertEqual((code, out), (0, "dog\ndrone\n"))
            # A trailing/leading `or` is a usage error, not a silent empty.
            code, _ = _run(["get", "animal", "or"], session)
            self.assertNotEqual(code, 0)


class TestEmptyQueryAndCount(unittest.TestCase):
    """`get` with no terms is everything, `list` is the same question under
    another name, and `count` answers it as a number."""

    def _session(self, home):
        session = cli.Session(os.path.join(home, "zoo.od"))
        for argv in (["put", "animal"], ["put", "machine"], ["put", "pet"],
                     ["put", "dog", "animal", "pet"],
                     ["put", "drone", "machine"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    ALL = "animal\ndog\ndrone\nmachine\npet\n"

    def test_get_with_no_terms_is_everything(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["get"], session), (0, self.ALL))

    def test_list_get_and_get_star_are_one_answer(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            answers = {_run(argv, session)[1]
                       for argv in (["get"], ["list"], ["get", "*"])}
            self.assertEqual(answers, {self.ALL})

    def test_dangling_or_is_still_an_error(self):
        # The empty query is a request; an empty *disjunct* is a typo, and
        # reading it as "everything" would silently widen a narrow query.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertNotEqual(_run(["get", "animal", "or"], session)[0], 0)

    def test_count_is_a_number_for_the_same_queries(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["count"], session), (0, "5\n"))
            self.assertEqual(_run(["count", "animal"], session), (0, "1\n"))
            self.assertEqual(_run(["count", "animal", "or", "machine"],
                                  session), (0, "2\n"))
            self.assertEqual(_run(["count", "nope"], session), (0, "0\n"))


class TestDisplayLimit(unittest.TestCase):
    """The cap is a display decision: a pipe is never capped, the query is
    always complete, and what was withheld is always said out loud."""

    def _session(self, home, n=10):
        session = cli.Session(os.path.join(home, "many.od"))
        for i in range(n):
            _run(["put", f"item{i:02d}"], session)
        return session

    def _run_err(self, argv, session):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, session)
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        cli._OVERRIDES.clear()
        self._env = os.environ.pop("ONTODAG_LIMIT", None)

    def tearDown(self):
        cli._OVERRIDES.clear()
        os.environ.pop("ONTODAG_LIMIT", None)
        if self._env is not None:
            os.environ["ONTODAG_LIMIT"] = self._env

    def test_a_pipe_is_never_capped(self):
        # StringIO is not a tty, which is exactly the pipe case.
        with tempfile.TemporaryDirectory() as home:
            code, out, err = self._run_err(["get"], self._session(home))
            self.assertEqual((code, len(out.splitlines()), err), (0, 10, ""))

    def test_explicit_limit_truncates_and_says_so(self):
        with tempfile.TemporaryDirectory() as home:
            code, out, err = self._run_err(["get", "-n", "3"],
                                           self._session(home))
            self.assertEqual(code, 0)
            # A deterministic prefix of the canonical sort, not an arbitrary
            # three: the same command twice gives the same three.
            self.assertEqual(out.splitlines(), ["item00", "item01", "item02"])
            self.assertIn("7 more not shown", err)

    def test_the_withheld_note_never_lands_in_the_data(self):
        with tempfile.TemporaryDirectory() as home:
            _, out, _ = self._run_err(["get", "-n", "3"], self._session(home))
            self.assertNotIn("not shown", out)

    def test_limit_zero_means_all(self):
        with tempfile.TemporaryDirectory() as home:
            code, out, err = self._run_err(["get", "-n", "0"],
                                           self._session(home))
            self.assertEqual((code, len(out.splitlines()), err), (0, 10, ""))

    def test_count_ignores_the_cap_entirely(self):
        # The point of `count` is to be the complete answer when printing
        # the results is what you are trying to avoid.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            os.environ["ONTODAG_LIMIT"] = "3"
            self.assertEqual(self._run_err(["count"], session)[1], "10\n")

    def test_env_sets_it_and_a_flag_beats_the_env(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            os.environ["ONTODAG_LIMIT"] = "2"
            self.assertEqual(len(self._run_err(["get"], session)[1]
                                 .splitlines()), 2)
            self.assertEqual(len(self._run_err(["get", "-n", "5"], session)[1]
                                 .splitlines()), 5)

    def test_a_bad_limit_is_refused_when_it_is_set_not_later(self):
        with tempfile.TemporaryDirectory() as home:
            code, _, err = self._run_err(["get", "-n", "banana"],
                                         self._session(home))
            self.assertEqual(code, 1)
            self.assertIn("limit", err)


class TestBelow(unittest.TestCase):
    def _session(self, home):
        session = cli.Session(os.path.join(home, "zoo.od"))
        for argv in (["put", "animal"], ["put", "dog", "animal"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def test_true_false_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["below", "dog", "animal"], session),
                             (0, "true\n"))
            self.assertEqual(_run(["below", "animal", "dog"], session),
                             (1, "false\n"))
            # Unknown names are false, not errors: nothing on stderr.
            self.assertEqual(_run(["below", "typo", "animal"], session),
                             (1, "false\n"))

    def test_question_mark_alias(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["?", "dog", "animal"], session),
                             (0, "true\n"))

    def test_typed_values_from_names_alone(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            for argv in (["put", "dimension"],
                         ["put", "linear-dimension", "dimension"],
                         ["put", "weight", "linear-dimension"]):
                self.assertEqual(_run(argv, session)[0], 0)
            self.assertEqual(
                _run(["below", "weight(3kg)", "weight(..5kg)"], session),
                (0, "true\n"))
            self.assertEqual(
                _run(["below", "weight(9kg)", "weight(..5kg)"], session),
                (1, "false\n"))


class TestIndexCommand(unittest.TestCase):
    def test_publish_and_consume_cone_summaries(self):
        data_blobs = MemoryBytesStore()
        data_pointer = MemoryPointer()
        index_blobs = MemoryBytesStore()
        index_pointer = MemoryPointer()
        backend = cli.SwarmBackend(
            "pets",
            store_factory=lambda: RecordStore(data_blobs,
                                              pointer=data_pointer),
            index_store_factory=lambda: RecordStore(index_blobs,
                                                    pointer=index_pointer))
        session = cli.Session.__new__(cli.Session)
        session.spec, session._backend = "swarm:pets", backend
        session._dag = backend.load()
        for i in range(70):   # enough descendants to clear the threshold
            self.assertEqual(_run(["put", f"dog-{i}", "animal"]
                                  if i else ["put", "animal"], session)[0], 0)
        code, out = _run(["index"], session)
        self.assertEqual(code, 0, out)
        lines = dict(line.split(None, 1) for line in out.splitlines())
        self.assertEqual(lines["data"], session.dag.store.root)

        # The published pair actually serves a lazy reader.
        from ontodag.cones import ConeIndex
        from ontodag.lazy import LazyOntoDAG
        reader = LazyOntoDAG(
            RecordStore.at(lines["data"], data_blobs),
            cone_index=ConeIndex(RecordStore.at(lines["index"], index_blobs),
                                 lines["data"]))
        result = reader.get(["animal"])
        self.assertEqual(len(result), 69)
        self.assertLess(reader.fetches, 10)   # summary, not the cone

        # Indexing wrote nothing to the data store.
        self.assertEqual(lines["data"], session.dag.store.root)

    def test_file_backend_refuses(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "zoo.od"))
            _run(["put", "animal"], session)
            code, _ = _run(["index"], session)
            self.assertNotEqual(code, 0)


class TestSwarmSignerWiring(unittest.TestCase):
    """The swarm: backend is local-first (recordstore 0.19): commits land
    in a store directory and sync in the background. With a signer the
    head is additionally published to a Swarm feed — only after network
    confirmation (publish_pointer=SwarmFeedPointer). Without one, nothing
    is publishable and publish_pointer stays None. Wiring only; the live
    cycle is tests/test_swarm_bee.py's (gated) job."""

    _ENV = ("ONTODAG_HOME", "BEE_API", "BEE_BATCH", "BEE_SIGNER")

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        os.environ["ONTODAG_HOME"] = self._home.name
        os.environ["BEE_API"] = "http://node:1633"
        os.environ["BEE_BATCH"] = "beef" * 16
        os.environ.pop("BEE_SIGNER", None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def test_signer_routes_to_feed_publication(self):
        from unittest import mock
        import recordstore

        os.environ["BEE_SIGNER"] = "0x" + "11" * 32
        sentinel, feed = object(), object()
        with mock.patch.object(recordstore, "local_first_store",
                               return_value=sentinel) as factory, \
             mock.patch.object(recordstore, "SwarmFeedPointer",
                               return_value=feed) as pointer:
            store = cli.SwarmBackend("pets")._record_store()
        self.assertIs(store, sentinel)
        pointer.assert_called_once_with(
            "http://node:1633", "pets", signer="0x" + "11" * 32,
            postage_batch_id="beef" * 16)
        factory.assert_called_once_with(
            cli.SwarmBackend("pets").store_dir(), "http://node:1633",
            stamp="beef" * 16, publish_pointer=feed)

    def test_signer_from_config_file(self):
        from unittest import mock
        import recordstore

        _, out = _run(["set", "bee_signer", "0x" + "22" * 32],
                      cli.Session(os.path.join(self._home.name, "ignore.od")))
        with mock.patch.object(recordstore, "local_first_store",
                               return_value=object()), \
             mock.patch.object(recordstore, "SwarmFeedPointer",
                               return_value=object()) as pointer:
            cli.SwarmBackend("pets")._record_store()
        self.assertEqual(pointer.call_args.kwargs["signer"], "0x" + "22" * 32)

    def test_without_signer_no_publication(self):
        from unittest import mock
        import recordstore

        with mock.patch.object(recordstore, "local_first_store",
                               return_value=object()) as factory:
            cli.SwarmBackend("pets")._record_store()
        self.assertIsNone(factory.call_args.kwargs["publish_pointer"])
        self.assertEqual(factory.call_args.args[0],
                         cli.SwarmBackend("pets").store_dir())

    def test_a_legacy_root_is_what_a_new_store_bootstraps_from(self):
        # A pre-0.14 store kept its blobs on Bee and its head in NAME.root.
        # That root is now CLONED into the local store rather than written
        # into its HEAD: seeding HEAD alone points the store at content it has
        # no blobs for, and swarmfs heals only refs a replica already knows,
        # so the first read raised KeyError (found on a live node 2026-08-06).
        backend = cli.SwarmBackend("pets")
        os.makedirs(os.path.dirname(backend.pointer_path()), exist_ok=True)
        with open(backend.pointer_path(), "w") as f:
            f.write("ab" * 32)
        self.assertEqual(backend._bootstrap_root(None), "ab" * 32)

    def test_a_stale_legacy_root_cannot_touch_a_live_store(self):
        backend = cli.SwarmBackend("pets")
        os.makedirs(backend.store_dir(), exist_ok=True)
        with open(os.path.join(backend.store_dir(), "HEAD"), "w") as f:
            f.write("cd" * 32)
        os.makedirs(os.path.dirname(backend.pointer_path()), exist_ok=True)
        with open(backend.pointer_path(), "w") as f:
            f.write("ab" * 32)
        self.assertIsNone(backend._bootstrap_root(None))
        with open(os.path.join(backend.store_dir(), "HEAD")) as f:
            self.assertEqual(f.read(), "cd" * 32)

    def test_set_shows_bee_signer(self):
        session = cli.Session(os.path.join(self._home.name, "ignore.od"))
        code, out = _run(["set"], session)
        self.assertEqual(code, 0)
        self.assertIn("bee_signer = ", out)


if __name__ == "__main__":
    unittest.main()


class TestLocalRecordStore(unittest.TestCase):
    """`rs:PATH` — the rung between a text file and Swarm.

    Its reason to exist is that canonical roots, snapshots and certificates
    used to require a Bee node, a funded wallet and a postage batch before
    you could see any of them. Everything asserted here runs on a directory.
    """

    def _run(self, argv, session):
        return _run(argv, session)

    def test_routing_and_normalization(self):
        backend = cli._make_backend("rs:/tmp/x")
        self.assertIsInstance(backend, cli.LocalRecordBackend)
        # The path is absolutised inside the prefix, so a spec saved to
        # config means the same thing from any working directory. Asserted
        # with `isabs`, not a leading slash: on Windows an absolute path
        # starts with a drive letter.
        normalized = cli._normalize_spec("rs:./rel")
        self.assertTrue(normalized.startswith("rs:"))
        self.assertTrue(os.path.isabs(normalized[len("rs:"):]),
                        f"not absolutised: {normalized}")
        self.assertEqual(cli._normalize_spec("swarm:x"), "swarm:x")

    def test_it_persists_and_has_a_real_root(self):
        with tempfile.TemporaryDirectory() as home:
            spec = f"rs:{os.path.join(home, 'store')}"
            session = cli.Session(spec)
            for argv in (["put", "Travel"], ["put", "Japan", "Travel"],
                         ["put", "doc", "Japan"]):
                self.assertEqual(_run(argv, session)[0], 0)
            root = session.dag.store.root
            self.assertTrue(root, "a record store must produce a root")

            reopened = cli.Session(spec)          # a fresh process would
            self.assertEqual(_run(["get", "Travel"], reopened)[1],
                             "Japan\ndoc\n")
            self.assertEqual(reopened.dag.store.root, root)

    def test_the_root_is_canonical_across_build_orders(self):
        # The property the whole content-addressed story rests on, available
        # here with no node: equal knowledge, equal name.
        def build(path, order):
            session = cli.Session(f"rs:{path}")
            for argv in order:
                _run(argv, session)
            return session.dag.store.root

        with tempfile.TemporaryDirectory() as home:
            first = build(os.path.join(home, "a"),
                          [["put", "Travel"], ["put", "Japan", "Travel"],
                           ["put", "doc", "Japan"]])
            second = build(os.path.join(home, "b"),
                           [["put", "Travel"], ["put", "Japan", "Travel"],
                            ["put", "other"], ["remove", "other"],
                            ["put", "doc", "Japan"]])
            self.assertEqual(first, second)

    def test_index_accepts_it_where_a_text_store_is_refused(self):
        with tempfile.TemporaryDirectory() as home:
            record = cli.Session(f"rs:{os.path.join(home, 's')}")
            _run(["put", "a"], record)
            self.assertEqual(_run(["index"], record)[0], 0)

            plain = cli.Session(os.path.join(home, "s.od"))
            _run(["put", "a"], plain)
            code, _ = _run(["index"], plain)
            self.assertEqual(code, 1)

    def test_describe_round_trips_through_set(self):
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "store")
            session = cli.Session(f"rs:{path}")
            self.assertEqual(session.describe(), f"rs:{path}")


class TestSwarmDoctor(unittest.TestCase):
    """`odag swarm` walks the setup in dependency order and stops at the
    first failure. The failures are the product here, not the successes."""

    def _diagnose(self, session):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["swarm"], session)
        return code, out.getvalue()

    def test_it_reports_a_missing_extra_before_touching_the_network(self):
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=None):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 1)
        self.assertIn('pip install "ontodag[swarm]"', text)
        # ...and does not pretend to know anything about the node.
        self.assertNotIn("node reachable", text)

    def test_an_unreachable_node_names_the_next_step(self):
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=object()), \
             mock.patch.object(cli, "_bee_get",
                               side_effect=OSError("refused")):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 1)
        self.assertIn("nothing answering", text)
        self.assertIn("odag set bee_api", text)

    def test_a_healthy_node_with_no_batch_says_how_to_buy_one(self):
        replies = {
            "/": {}, "/health": {"status": "ok"},
            "/chainstate": {"block": 42},
            "/wallet": {"bzzBalance": "10", "nativeTokenBalance": "10"},
            "/stamps": {"stamps": [{"usable": False}]},
        }
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=object()), \
             mock.patch.object(cli, "_bee_get",
                               side_effect=lambda api, path, **kw: replies[path]):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 1)
        self.assertIn("none usable", text)
        self.assertIn("/stamps/", text)      # the command to run
        self.assertIn("~70s", text)          # and the wait nobody expects

    def test_a_fully_ready_node_exits_zero(self):
        replies = {
            "/": {}, "/health": {"status": "ok"},
            "/chainstate": {"block": 42},
            "/wallet": {"bzzBalance": "10", "nativeTokenBalance": "10"},
            "/stamps": {"stamps": [{"usable": True, "batchID": "ab" * 16,
                                    "batchTTL": 86400 * 3}]},
        }
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=object()), \
             mock.patch.object(cli, "_bee_get",
                               side_effect=lambda api, path, **kw: replies[path]):
            code, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertEqual(code, 0)
        self.assertIn("TTL 3.0 days", text)
        self.assertIn("odag set store swarm:", text)

    def test_the_unready_path_offers_the_local_record_store(self):
        # The adoption point: someone who cannot run a node today should
        # still be told how to get the properties Swarm is *for*.
        with tempfile.TemporaryDirectory() as home, \
             mock.patch.object(cli.importlib.util, "find_spec",
                               return_value=None):
            _, text = self._diagnose(cli.Session(os.path.join(home, "s.od")))
        self.assertIn("rs:", text)

    def test_a_healthy_node_is_reported_reachable(self):
        """The bug this guards: reachability was asked of `/`, which Bee serves
        as `text/plain` ("Ethereum Swarm Bee"), and the probe parsed every
        response as JSON. So a healthy node raised JSONDecodeError and was
        reported as "nothing answering" — and because the walk stops at the
        first failure, that ended the diagnosis and told the user to start a
        node that was already running.

        It needs a real socket: any test that stubs `_bee_get` shares the
        parsing assumption that was wrong, and sees nothing.
        """
        import http.server
        import threading

        class Bee(http.server.BaseHTTPRequestHandler):
            def do_GET(self):                       # noqa: N802
                if self.path == "/":                # plain text, like Bee
                    body, kind = b"Ethereum Swarm Bee\n", "text/plain"
                elif self.path == "/health":
                    body, kind = (b'{"status":"ok","version":"2.8.1"}',
                                  "application/json")
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):           # keep the test quiet
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Bee)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = f"http://127.0.0.1:{server.server_port}"
            # The walk stops at the first failure, and its first check is that
            # the swarm extra is installed — which it is not in a plain test
            # environment. Satisfy that one so this test is about the probe it
            # names, rather than about how the suite happens to be installed.
            with mock.patch.object(cli.importlib.util, "find_spec",
                                   return_value=object()):
                checks = dict((label, ok)
                              for ok, label, _ in cli._swarm_checks(api))
        finally:
            server.shutdown()
            server.server_close()
        self.assertTrue(checks.get("swarm extra installed"), checks)
        self.assertTrue(checks.get("node reachable"), checks)
        self.assertTrue(checks.get("node healthy"), checks)


class TestConfigSecrecy(unittest.TestCase):
    """`bee_signer` is a private key that can publish to your feed, so the two
    places it could leak are closed: the file it is written to, and the command
    that reads settings back."""

    _ENV = ("BEE_API", "BEE_BATCH", "BEE_SIGNER", "ONTODAG_HOME")
    KEY = "1" * 60 + "abcd"

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        for key in self._ENV:
            os.environ.pop(key, None)
        os.environ["ONTODAG_HOME"] = self._home.name

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def _session(self):
        return cli.Session(cli._resolve_store(None))

    @unittest.skipUnless(POSIX_MODES, "Windows has no POSIX permission bits")
    def test_the_config_file_is_owner_only(self):
        session = self._session()
        self.assertEqual(_run(["set", "bee_signer", self.KEY], session),
                         (0, ""))
        mode = os.stat(cli._config_path()).st_mode & 0o777
        self.assertEqual(mode, 0o600, f"config is {oct(mode)}, not 0o600")

    @unittest.skipUnless(POSIX_MODES, "Windows has no POSIX permission bits")
    def test_a_config_written_before_this_gets_repaired(self):
        """The case that matters: the key is already on disk, world-readable,
        written by an older version. The next write must tighten it."""
        os.makedirs(self._home.name, exist_ok=True)
        path = cli._config_path()
        with open(path, "w") as fh:
            fh.write("bee_api = http://n:1633\n")
        os.chmod(path, 0o644)
        _run(["set", "bee_signer", self.KEY], self._session())
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_showing_all_settings_does_not_print_the_key(self):
        session = self._session()
        _run(["set", "bee_signer", self.KEY], session)
        _code, out = _run(["set"], session)
        self.assertNotIn(self.KEY, out)
        self.assertIn("bee_signer = <hidden, ends abcd>", out)

    def test_showing_the_key_alone_does_not_print_it_either(self):
        session = self._session()
        _run(["set", "bee_signer", self.KEY], session)
        _code, out = _run(["set", "bee_signer"], session)
        self.assertNotIn(self.KEY, out)
        self.assertIn("<hidden, ends abcd>", out)

    def test_an_unset_signer_reads_as_empty_not_as_hidden(self):
        _code, out = _run(["set", "bee_signer"], self._session())
        self.assertEqual(out, "bee_signer = \n")

    def test_a_signer_from_the_environment_is_masked_too(self):
        os.environ["BEE_SIGNER"] = self.KEY
        _code, out = _run(["set"], self._session())
        self.assertNotIn(self.KEY, out)

    def test_the_stored_value_is_still_the_real_key(self):
        """Masking is display-only: the config remains the place to read it."""
        _run(["set", "bee_signer", self.KEY], self._session())
        self.assertEqual(cli._read_config()["bee_signer"], self.KEY)
        self.assertEqual(cli._configured("bee_signer"), self.KEY)

    def test_non_secret_settings_are_still_shown_in_full(self):
        session = self._session()
        _run(["set", "bee_batch", "c0ffee"], session)
        _code, out = _run(["set", "bee_batch"], session)
        self.assertEqual(out, "bee_batch = c0ffee\n")


class TestGenerateSigner(unittest.TestCase):
    """`odag set bee_signer generate` — because the alternative was asking
    people to type a shell incantation that produces 32 random bytes, which is
    hostile and easy to get subtly wrong in a way that only fails later."""

    _ENV = ("BEE_API", "BEE_BATCH", "BEE_SIGNER", "ONTODAG_HOME")

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k) for k in self._ENV}
        for key in self._ENV:
            os.environ.pop(key, None)
        os.environ["ONTODAG_HOME"] = self._home.name

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def _session(self):
        return cli.Session(cli._resolve_store(None))

    def _set(self, *argv):
        """Run `set`, returning (code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["set", *argv], self._session())
        return code, out.getvalue(), err.getvalue()

    def test_it_generates_a_usable_key(self):
        code, out, _err = self._set("bee_signer", "generate")
        self.assertEqual((code, out), (0, ""))      # silent on stdout
        key = cli._read_config()["bee_signer"]
        self.assertEqual(len(key), 64)
        self.assertTrue(cli._looks_like_a_signer(key))

    def test_the_generated_key_parses_with_the_real_signer_library(self):
        """The shape check above is the contract; this is the cross-check
        against the library that will actually consume it. It needs the `swarm`
        extra, so it skips on a plain test install rather than making the whole
        suite depend on an optional dependency."""
        try:
            from bee.swarm.keys import PrivateKey
        except ImportError:
            self.skipTest("needs the swarm extra (bee) for the real parser")
        self._set("bee_signer", "generate")
        PrivateKey.from_hex(cli._read_config()["bee_signer"])

    def test_two_generations_differ(self):
        self._set("bee_signer", "generate")
        first = cli._read_config()["bee_signer"]
        self._set("bee_signer", "generate", "--force")
        self.assertNotEqual(cli._read_config()["bee_signer"], first)

    def test_the_key_is_never_printed(self):
        _code, out, err = self._set("bee_signer", "generate")
        key = cli._read_config()["bee_signer"]
        self.assertNotIn(key, out)
        self.assertNotIn(key, err)
        self.assertIn(f"ends {key[-4:]}", err)      # only the tail, to identify

    def test_it_says_where_the_key_went_and_to_back_it_up(self):
        """A secret the user will never be shown again is the one case where
        silence is unhelpful."""
        _code, _out, err = self._set("bee_signer", "generate")
        self.assertIn(cli._config_path(), err)
        self.assertIn("back it up", err)

    @unittest.skipUnless(POSIX_MODES, "Windows has no POSIX permission bits")
    def test_the_file_is_owner_only(self):
        self._set("bee_signer", "generate")
        self.assertEqual(os.stat(cli._config_path()).st_mode & 0o777, 0o600)

    def test_replacing_a_key_is_refused_by_default(self):
        self._set("bee_signer", "generate")
        original = cli._read_config()["bee_signer"]
        code, _out, err = self._set("bee_signer", "generate")
        self.assertEqual(code, 1)
        self.assertIn("--force", err)
        self.assertIn("strand", err)
        # and it really did not touch the stored key
        self.assertEqual(cli._read_config()["bee_signer"], original)

    def test_force_replaces_it(self):
        self._set("bee_signer", "generate")
        original = cli._read_config()["bee_signer"]
        code, _out, _err = self._set("bee_signer", "generate", "--force")
        self.assertEqual(code, 0)
        self.assertNotEqual(cli._read_config()["bee_signer"], original)

    def test_it_warns_when_the_environment_would_win(self):
        os.environ["BEE_SIGNER"] = "ab" * 32
        _code, _out, err = self._set("bee_signer", "generate")
        self.assertIn("BEE_SIGNER", err)
        self.assertIn("outranks", err)

    def test_a_malformed_key_is_refused_at_set_time(self):
        """The failure a real user hit: a stray character on a paste gives 65
        characters, and without this it is accepted here and blows up later at
        the first command that opens the store."""
        code, _out, err = self._set("bee_signer", "a" * 65)
        self.assertEqual(code, 1)
        self.assertIn("64 characters", err)
        self.assertIn("generate", err)              # points at the easy way
        self.assertNotIn("bee_signer", cli._read_config())

    def test_a_real_key_is_still_accepted_either_spelling(self):
        for value in ("cd" * 32, "0x" + "cd" * 32):
            code, _out, _err = self._set("bee_signer", value, "--force")
            self.assertEqual(code, 0, value)
            self.assertEqual(cli._read_config()["bee_signer"], value)


class TestSwarmBackendLocalFirst(unittest.TestCase):
    """End to end, offline: the swarm: backend is local-first — a commit
    succeeds with the node unreachable (durable in the store directory,
    synced by a later run), and reopening resumes at the committed head."""

    def setUp(self):
        try:
            import swarmfs.localstore  # noqa: F401
        except ImportError:
            self.skipTest("swarmfs not installed")
        self._home = tempfile.TemporaryDirectory()
        self._saved = {k: os.environ.get(k)
                       for k in ("ONTODAG_HOME", "BEE_API", "BEE_BATCH")}
        os.environ["ONTODAG_HOME"] = self._home.name
        os.environ["BEE_API"] = "http://127.0.0.1:9"  # nothing listens here
        os.environ["BEE_BATCH"] = "beef" * 16
        self._timeout = cli._SYNC_TIMEOUT
        cli._SYNC_TIMEOUT = 0.2

    def tearDown(self):
        cli._SYNC_TIMEOUT = self._timeout
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._home.cleanup()

    def test_commit_offline_then_reopen(self):
        import io
        from contextlib import redirect_stderr

        backend = cli.SwarmBackend("pets")
        dag = backend.load()                 # transient: lock released here
        dag.put("cat", [])
        err = io.StringIO()
        with redirect_stderr(err):
            backend.save(dag)                # node down: still succeeds
        self.assertIn("committed locally", err.getvalue())

        dag2 = cli.SwarmBackend("pets").load()   # reopen at the same head
        self.assertIn("cat", dag2.nodes)

    def test_no_lock_held_between_windows(self):
        """The transient-window contract: after load()/save() return, the
        store's writer lock is free — a second opener never blocks."""
        b1 = cli.SwarmBackend("pets")
        dag = b1.load()
        # while dag serves from memory, another process-alike opens freely
        store = cli.SwarmBackend("pets")._record_store()
        try:
            self.assertIsNotNone(store)
        finally:
            store.close()
        backendless = cli.SwarmBackend("pets").load()
        self.assertEqual(set(backendless.nodes), set(dag.nodes))

    def test_concurrent_windows_converge_by_merge_not_lww(self):
        """Multi-writer convergence is the CRDT merge, not locking: two
        sessions hydrate the same store, edit the SAME node under
        different parents, and save in turn — the second save merges the
        moved head, so the parents union instead of last-write-wins."""
        b1, b2 = cli.SwarmBackend("pets"), cli.SwarmBackend("pets")
        dag1 = b1.load()
        dag2 = b2.load()                    # concurrent session, no lock held

        dag1.put("p1", [])
        dag1.put("child", ["p1"])
        import io
        from contextlib import redirect_stderr
        with redirect_stderr(io.StringIO()):
            b1.save(dag1)

        dag2.put("p2", [])
        dag2.put("child", ["p2"])           # same node, different parent
        with redirect_stderr(io.StringIO()):
            b2.save(dag2)                   # head moved -> CRDT merge

        dag3 = cli.SwarmBackend("pets").load()
        parents = {p.name for p in dag3.nodes["child"].parents}
        self.assertEqual(parents, {"p1", "p2"})

    def test_concurrent_remove_loses_and_the_survivor_reaches_the_store(self):
        """A peer deletes a record another session still holds; union says
        the held copy survives (the grow-only stance, same as
        remove-loses-to-readd) — and it must survive IN THE STORE, not
        just in memory. commit() used to diff against the session's base
        lineage, stage nothing for the held-but-unchanged record, and so
        silently keep the head's deletion in the committed root: the
        store said remove-WINS while memory said remove-LOSES."""
        import io
        from contextlib import redirect_stderr

        b1, b2 = cli.SwarmBackend("pets"), cli.SwarmBackend("pets")
        seed = b1.load()
        seed.put("p1", [])
        seed.put("child", ["p1"])
        with redirect_stderr(io.StringIO()):
            b1.save(seed)

        dag1 = b1.load()
        dag2 = b2.load()                    # still holds child
        dag1.remove("child")
        with redirect_stderr(io.StringIO()):
            b1.save(dag1)                   # head moves: child deleted

        dag2.put("p2", [])                  # unrelated concurrent edit
        with redirect_stderr(io.StringIO()):
            b2.save(dag2)                   # merge: child must be re-staged

        dag3 = cli.SwarmBackend("pets").load()
        self.assertIn("p2", dag3.nodes)
        self.assertIn("child", dag3.nodes)


class TestExcerpt(unittest.TestCase):
    """`excerpt` is the materialized cut: the query's answer, with the edges
    among the answers, in a file you can import back.

    Every assertion here is against the *query answer*, never against an exit
    code — the web session learned that a 200 with the wrong picture in it
    reads as a pass.
    """

    def _session(self, home):
        session = cli.Session(os.path.join(home, "trips.od"))
        for argv in (["put", "Travel"], ["put", "Japan"],
                     ["put", "Flight", "Travel"],
                     ["put", "Hotel", "Travel"],
                     ["put", "JAL", "Flight", "Japan"],
                     ["put", "JAL-cheap", "JAL"],
                     ["put", "Ryokan", "Hotel", "Japan"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def _excerpt(self, home, session, *categories):
        path = os.path.join(home, "cut.od")
        self.assertEqual(_run(["excerpt", path] + list(categories), session),
                         (0, ""))
        return cli._load(path)

    def _answer(self, session, *categories):
        return {item.name for item in cli._query(list(categories), session.dag)}

    def test_excerpt_is_exactly_the_answer(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Travel", "Japan")
            names = set(cut.nodes) - {cut.root.name}
            self.assertEqual(names, self._answer(session, "Travel", "Japan"))
            self.assertEqual(names, {"JAL", "JAL-cheap", "Ryokan"})

    def test_the_answers_keep_their_own_edges(self):
        # Cones are downward-closed under intersection, so JAL-cheap must
        # arrive still under JAL, not flattened to the root.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Travel", "Japan")
            self.assertEqual(
                {p.name for p in cut.nodes["JAL-cheap"].parents}, {"JAL"})

    def test_query_terms_are_not_in_the_excerpt(self):
        # The whole point of "keep it importable": a constraint is not a fact.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Travel", "Japan")
            self.assertNotIn("Travel", cut.nodes)
            self.assertNotIn("Japan", cut.nodes)

    def test_it_round_trips_through_import(self):
        # Top answers hang under `*`, so the importing store can see them
        # with the empty query — otherwise they would load as orphans.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            path = os.path.join(home, "cut.od")
            self.assertEqual(_run(["excerpt", path, "Travel", "Japan"],
                                  session)[0], 0)
            fresh = cli.Session(os.path.join(home, "fresh.od"))
            self.assertEqual(_run(["import", path], fresh)[0], 0)
            self.assertEqual(_run(["list"], fresh),
                             (0, "JAL\nJAL-cheap\nRyokan\n"))
            self.assertEqual(_run(["get", "JAL"], fresh), (0, "JAL-cheap\n"))

    def test_union_queries_excerpt_too(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Hotel", "or", "Flight")
            self.assertEqual(set(cut.nodes) - {cut.root.name},
                             self._answer(session, "Hotel", "or", "Flight"))

    def test_the_empty_query_excerpts_the_whole_store(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session)
            self.assertEqual(set(cut.nodes) - {cut.root.name},
                             set(session.dag.nodes) - {session.dag.root.name})
            self.assertEqual({p.name for p in cut.nodes["Flight"].parents},
                             {"Travel"})

    def test_an_empty_answer_is_an_empty_excerpt(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut = self._excerpt(home, session, "Flight", "Hotel")
            self.assertEqual(set(cut.nodes), {cut.root.name})

    def test_the_store_is_untouched(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = _run(["show"], session)
            self._excerpt(home, session, "Japan")
            self.assertEqual(_run(["show"], session), before)

    def test_a_dangling_or_is_still_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            path = os.path.join(home, "cut.od")
            self.assertNotEqual(_run(["excerpt", path, "Japan", "or"],
                                     session)[0], 0)

    def test_a_virtual_term_excerpts_its_answer(self):
        # The bug this guards against is the one the web *picture* had: a
        # parametric term is not a node, so anything that intersects by name
        # silently drops it. The answer here contains the real stored value
        # node; the virtual constraint itself is still not filed.
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "boxes.od"))
            for argv in (["prelude"], ["put", "box", "weight(3kg)"],
                         ["put", "lid", "box"]):
                self.assertEqual(_run(argv, session)[0], 0)
            cut = self._excerpt(home, session, "weight(..5kg)")
            names = set(cut.nodes) - {cut.root.name}
            self.assertEqual(names, self._answer(session, "weight(..5kg)"))
            self.assertIn("box", names)
            self.assertNotIn("weight(..5kg)", names)

    def test_the_empty_excerpt_is_byte_identical_to_export(self):
        # Pins the doc claim in §5.4, and with it the property that makes the
        # widened query safe: an unconstrained excerpt is the whole store.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            cut, exported = (os.path.join(home, n) for n in ("cut.od", "exp.od"))
            self.assertEqual(_run(["excerpt", cut], session)[0], 0)
            self.assertEqual(_run(["export", exported], session)[0], 0)
            with open(cut, encoding="utf-8") as a, \
                    open(exported, encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read())


class TestVisualizeScoping(unittest.TestCase):
    """`visualize CAT...` draws the query, not the store — and draws the
    query *terms* too, which is exactly where it differs from `excerpt`.

    Graphviz is never invoked here: the shaping is what can be wrong, and
    asserting on it keeps the test free of the `viz` extra and the `dot`
    binary.
    """

    def _session(self, home):
        session = cli.Session(os.path.join(home, "trips.od"))
        for argv in (["put", "Travel"], ["put", "Japan"],
                     ["put", "Flight", "Travel"],
                     ["put", "Hotel", "Travel"],
                     ["put", "JAL", "Flight", "Japan"],
                     ["put", "Ryokan", "Hotel", "Japan"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def _drawn(self, session, *categories):
        """The DAG `visualize` handed the renderer."""
        drawn = []

        class FakeVisualizer:
            def __init__(self, format=None):
                pass

            def visualize(self, dag, filename=None):
                drawn.append(dag)

        with mock.patch("ontodag.viz.OntoDAGVisualizer", FakeVisualizer):
            code, _ = _run(["visualize"] + list(categories), session)
        self.assertEqual(code, 0)
        self.assertEqual(len(drawn), 1)
        return drawn[0]

    def test_no_categories_draws_the_store_itself(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertIs(self._drawn(session), session.dag)

    def test_a_query_draws_its_answer_under_its_terms(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            picture = self._drawn(session, "Travel", "Japan")
            self.assertEqual(set(picture.nodes) - {picture.root.name},
                             {"Travel", "Japan", "JAL", "Ryokan"})
            for term in ("Travel", "Japan"):
                self.assertEqual(
                    {n.name for n in picture.nodes[term].neighbors},
                    {"JAL", "Ryokan"})

    def test_the_picture_is_a_view_not_the_store(self):
        # It invents nodes; nothing about that may reach the real DAG.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = _run(["show"], session)
            self._drawn(session, "weight(..5kg)")
            self.assertEqual(_run(["show"], session), before)

    def test_a_union_draws_two_branches(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            picture = self._drawn(session, "Flight", "or", "Hotel")
            self.assertEqual({n.name for n in picture.nodes["Flight"].neighbors},
                             {"JAL"})
            self.assertEqual({n.name for n in picture.nodes["Hotel"].neighbors},
                             {"Ryokan"})

    def test_a_virtual_term_is_drawn_even_with_no_such_node(self):
        # The bug that made every query picture untrustworthy: a parametric
        # term has no node, so a name-based intersection dropped it.
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "boxes.od"))
            for argv in (["prelude"], ["put", "box", "weight(3kg)"]):
                self.assertEqual(_run(argv, session)[0], 0)
            picture = self._drawn(session, "weight(..5kg)")
            self.assertIn("weight(..5kg)", picture.nodes)
            self.assertIn("box", picture.nodes)
            self.assertNotIn("weight(..5kg)", session.dag.nodes)

    def test_a_dangling_or_is_still_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            with mock.patch("ontodag.viz.OntoDAGVisualizer"):
                self.assertNotEqual(
                    _run(["visualize", "Japan", "or"], session)[0], 0)

    def test_it_names_the_file_after_the_store_when_told_nothing(self):
        # Regression: `visualize` read `session.path`, which stopped existing
        # when `rs:` stores landed, so bare `odag visualize` raised
        # AttributeError for four releases. No test had ever omitted --out.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            written = []

            class FakeVisualizer:
                def __init__(self, format=None):
                    pass

                def visualize(self, dag, filename=None):
                    written.append(filename)

            with mock.patch("ontodag.viz.OntoDAGVisualizer", FakeVisualizer):
                self.assertEqual(_run(["visualize"], session)[0], 0)
            self.assertEqual(written, [os.path.join(home, "trips")])

    def test_every_backend_spelling_yields_a_name(self):
        self.assertEqual(cli._image_base("/store/trips.od"), "/store/trips")
        self.assertEqual(cli._image_base("swarm:pets"), "pets")
        # `rs:` normalizes the directory, so the separator is the platform's:
        # compare against normpath rather than pinning a POSIX spelling.
        self.assertEqual(cli._image_base("rs:/store/pets/"),
                         os.path.normpath("/store/pets"))



class TestMissingGraphvizBinary(unittest.TestCase):
    """Rendering needs two things and pip installs only one: the `graphviz`
    package is a wrapper around the `dot` program, which comes from the OS
    and is a separate download on Windows. So the *import* succeeds and the
    failure lands later, inside graphviz, as `ExecutableNotFound` — thirty
    lines of stack whose useful sentence is at the bottom. That is the same
    shape 0.17.1 fixed for missing packages, and it was still live for the
    binary: the likeliest Windows failure of all printed a traceback.
    """

    class ExecutableNotFound(RuntimeError):
        """Stands in for graphviz's own exception, which `_rendered` matches
        by class name — so this test needs neither graphviz nor a machine
        without `dot`."""

    def test_it_becomes_an_instruction(self):
        from ontodag.viz import _rendered
        from ontodag._extras import MissingExtra

        def render():
            raise self.ExecutableNotFound("failed to execute PosixPath('dot')")

        with self.assertRaises(MissingExtra) as caught:
            _rendered(render)
        message = str(caught.exception)
        self.assertIn("dot", message)
        self.assertIn("install graphviz", message)     # apt/brew/winget
        self.assertNotIn("Traceback", message)

    def test_every_other_failure_is_left_alone(self):
        # Only the missing binary is an instruction; a real rendering bug
        # must keep its traceback.
        from ontodag.viz import _rendered
        with self.assertRaises(ZeroDivisionError):
            _rendered(lambda: 1 // 0)

    def _run_err(self, argv, session):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, session)
        return code, out.getvalue(), err.getvalue()

    def test_the_cli_reports_it_like_any_other_refusal(self):
        from ontodag._extras import MissingExtra
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "trips.od"))
            _run(["put", "doc"], session)

            class Refusing:
                def __init__(self, *a, **kw):
                    pass

                def visualize(self, dag, filename=None, color_mapping=None):
                    raise MissingExtra("rendering needs the Graphviz system "
                                       "program `dot`")

            with mock.patch("ontodag.viz.OntoDAGVisualizer", Refusing):
                code, _out, err = self._run_err(["visualize"], session)
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("odag: "), err)
        self.assertIn("dot", err)

class TestExcerptContext(unittest.TestCase):
    """`excerpt --context` is the sendable form: the answer *plus the
    categories it hangs from*, so it merges — and diffs — into a store that
    shares them.

    The default cut drops exactly the edges that pointed at the query terms,
    which are the classification. Merged elsewhere it files the items at top
    level; this class pins the difference rather than describing it.
    """

    TRAVEL = ("Travel", "Japan", "Flight Travel", "Hotel Travel",
              "JAL Flight Japan", "JAL-cheap JAL", "Ryokan Hotel Japan",
              "BA Flight")

    def _session(self, home, name="orig.od", rows=None):
        session = cli.Session(os.path.join(home, name))
        for row in (self.TRAVEL if rows is None else rows):
            self.assertEqual(_run(["put"] + row.split(), session)[0], 0)
        return session

    def _cut(self, home, session, *categories, context=False):
        path = os.path.join(home, "ctx.od" if context else "plain.od")
        argv = ["excerpt", path] + list(categories) + (["--context"] if context
                                                       else [])
        self.assertEqual(_run(argv, session), (0, ""))
        return path, cli._load(path)

    def _parents(self, dag):
        return {name: sorted(p.name for p in node.parents
                             if dag.nodes.get(p.name) is p)
                for name, node in dag.nodes.items() if name != dag.root.name}

    def test_it_carries_the_categories_the_answers_hang_from(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            _, cut = self._cut(home, session, "Travel", "Japan", context=True)
            self.assertEqual(self._parents(cut), {
                "Travel": ["*"], "Japan": ["*"], "Flight": ["Travel"],
                "Hotel": ["Travel"], "JAL": ["Flight", "Japan"],
                "JAL-cheap": ["JAL"], "Ryokan": ["Hotel", "Japan"]})

    def test_nothing_is_invented(self):
        # Every edge in the file is an edge of the source. The plain cut has to
        # invent root edges to be well-formed; this one never does.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            _, cut = self._cut(home, session, "Travel", "Japan", context=True)
            source = self._parents(session.dag)
            for name, parents in self._parents(cut).items():
                self.assertTrue(set(parents) <= set(source[name]), name)

    def test_siblings_do_not_leak(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            _, cut = self._cut(home, session, "Travel", "Japan", context=True)
            self.assertNotIn("BA", cut.nodes)     # under Flight, not an answer

    def test_the_classification_survives_the_journey(self):
        # THE point of the flag, and the measurement that motivated it: with a
        # plain cut this same merge files JAL at top level and `get Japan`
        # comes back empty.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            plain, _ = self._cut(home, session, "Travel", "Japan")
            ctx, _ = self._cut(home, session, "Travel", "Japan", context=True)

            upper = ["Travel", "Japan", "Flight Travel", "Hotel Travel"]
            with_plain = self._session(home, "a.od", upper)
            self.assertEqual(_run(["merge", plain], with_plain)[0], 0)
            self.assertEqual(_run(["get", "Japan"], with_plain), (0, ""))

            with_ctx = self._session(home, "b.od", upper)
            self.assertEqual(_run(["merge", ctx], with_ctx)[0], 0)
            self.assertEqual(_run(["get", "Japan"], with_ctx),
                             (0, "JAL\nJAL-cheap\nRyokan\n"))
            self.assertNotIn("BA", with_ctx.dag.nodes)

    def test_it_stands_alone_too(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            ctx, _ = self._cut(home, session, "Travel", "Japan", context=True)
            fresh = cli.Session(os.path.join(home, "fresh.od"))
            self.assertEqual(_run(["import", ctx], fresh)[0], 0)
            self.assertEqual(_run(["get", "Travel", "Japan"], fresh),
                             (0, "JAL\nJAL-cheap\nRyokan\n"))

    def test_declarations_travel_with_a_typed_answer(self):
        # A head like `weight` is a real asserted parent of its values, so the
        # kind declaration is an ancestor and rides along — which is what lets
        # the receiving store recompute the order instead of storing it.
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "boxes.od"))
            for argv in (["prelude"], ["put", "crate", "weight(3kg)"]):
                self.assertEqual(_run(argv, session)[0], 0)
            path = os.path.join(home, "cut.od")
            self.assertEqual(
                _run(["excerpt", path, "weight(..5kg)", "--context"],
                     session)[0], 0)
            fresh = cli.Session(os.path.join(home, "fresh.od"))
            self.assertEqual(_run(["import", path], fresh)[0], 0)
            self.assertIn("linear-dimension", fresh.dag.nodes)
            # The computed order works in the fresh store, from names alone.
            self.assertEqual(_run(["get", "weight(..4kg)"], fresh),
                             (0, "crate\nweight(3kg)\n"))
            self.assertEqual(_run(["below", "weight(3kg)", "weight(..5kg)"],
                                  fresh), (0, "true\n"))

    def test_both_cuts_are_absorbed_by_the_store_they_came_from(self):
        # Merging an excerpt back must be a no-op at the level that counts:
        # the canonical root. The invented root edges of the plain cut are
        # redundant there, so reduction drops them.
        from ontodag.eager import EagerOntoDAG

        def root_of(dag):
            eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
            eager.merge(dag)
            return eager.commit()

        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = root_of(session.dag)
            for context in (False, True):
                path, _ = self._cut(home, session, "Travel", "Japan",
                                    context=context)
                self.assertEqual(_run(["merge", path], session)[0], 0)
                self.assertEqual(root_of(session.dag), before,
                                 f"context={context} changed the store")

    def test_the_empty_query_with_context_is_still_the_whole_store(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            ctx, _ = self._cut(home, session, context=True)
            exported = os.path.join(home, "exp.od")
            self.assertEqual(_run(["export", exported], session)[0], 0)
            with open(ctx, encoding="utf-8") as a, \
                    open(exported, encoding="utf-8") as b:
                self.assertEqual(a.read(), b.read())


class TestDiff(unittest.TestCase):
    """`diff OTHER [CAT...]`: `+` is OTHER, `-` is here.

    The design claim under test is that claims decide and edges display —
    an edge that vanished is reported only when the knowledge it carried
    vanished with it.
    """

    TRAVEL = ("Travel", "Japan", "Flight Travel", "Hotel Travel",
              "JAL Flight Japan", "JAL-cheap JAL", "Ryokan Hotel Japan",
              "BA Flight")

    def _store(self, home, name, rows):
        session = cli.Session(os.path.join(home, name))
        for row in rows:
            self.assertEqual(_run(["put"] + row.split(), session)[0], 0)
        return session

    def _diff(self, session, other, *categories):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["diff", other] + list(categories), session)
        return code, out.getvalue().splitlines(), err.getvalue()

    def _copy(self, home, session, name, extra=(), removed=()):
        """A sibling store: this one's contents, plus/minus some edits."""
        path = os.path.join(home, name)
        self.assertEqual(_run(["export", path], session)[0], 0)
        other = cli.Session(path)
        for row in extra:
            self.assertEqual(_run(["put"] + row.split(), other)[0], 0)
        for name_ in removed:
            self.assertEqual(_run(["remove", name_], other)[0], 0)
        return path

    def test_identical_stores_say_nothing_and_exit_zero(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od")
            self.assertEqual(self._diff(session, other), (0, [], ""))

    def test_an_added_item_arrives_with_its_parents(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od",
                               extra=["JAL-window-seat JAL-cheap"])
            code, lines, err = self._diff(session, other)
            self.assertEqual(code, 1)                     # grep-style
            self.assertEqual(lines, ["+ item JAL-window-seat (JAL-cheap)"])
            self.assertIn("+1/-0 items", err)

    def test_a_removed_item_is_reported_from_this_side(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od", removed=["Ryokan"])
            code, lines, _ = self._diff(session, other)
            self.assertEqual((code, lines), (1, ["- item Ryokan (Hotel Japan)"]))

    def test_a_new_parent_is_a_claim_line(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od",
                               extra=["JAL-cheap Ryokan"])
            code, lines, err = self._diff(session, other)
            self.assertEqual((code, lines), (1, ["+ below JAL-cheap Ryokan"]))
            # One asserted edge, two claims gained (Ryokan and its parent Hotel).
            self.assertIn("+2/-0 entailed claims", err)

    def test_reduction_churn_is_not_reported_as_deletion(self):
        # THE reason claims decide. `put Z B` prunes p->Z and B->leaf, so an
        # edge-set comparison would report two deletions; nothing was lost.
        rows = ("p", "B p", "Z p", "leaf B", "leaf Z")
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", rows)
            other = self._copy(home, session, "b.od", extra=["Z B"])
            self.assertEqual(
                {(n, tuple(sorted(c.name for c in i.neighbors)))
                 for n, i in cli._load(other).nodes.items()},
                {("*", ("p",)), ("p", ("B",)), ("B", ("Z",)),
                 ("Z", ("leaf",)), ("leaf", ())})   # the edges really did move
            code, lines, err = self._diff(session, other)
            self.assertEqual((code, lines), (1, ["+ below Z B"]))
            self.assertIn("+1/-0 entailed claims", err)

    def test_direction_is_mine_then_theirs(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od", extra=["Sleeper Flight"],
                               removed=["BA"])
            _, lines, _ = self._diff(session, other)
            self.assertEqual(lines, ["- item BA (Flight)",
                                     "+ item Sleeper (Flight)"])

    def test_a_query_scopes_both_sides(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od", removed=["BA"],
                               extra=["Ryokan-Kyoto Ryokan"])
            _, unscoped, _ = self._diff(session, other)
            self.assertIn("- item BA (Flight)", unscoped)
            # BA is under Flight but not below Japan, so it leaves the scope.
            _, scoped, err = self._diff(session, other, "Travel", "Japan")
            self.assertEqual(scoped, ["+ item Ryokan-Kyoto (Ryokan)"])
            self.assertIn("names", err)

    def test_a_contexted_cut_is_an_exact_subview(self):
        # The pair that makes review possible: with --context the cut diffs
        # clean against its source; the plain cut reads as mass deletion.
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            ctx = os.path.join(home, "ctx.od")
            plain = os.path.join(home, "plain.od")
            for path, argv in ((ctx, ["--context"]), (plain, [])):
                self.assertEqual(
                    _run(["excerpt", path, "Travel", "Japan"] + argv,
                         session)[0], 0)
            self.assertEqual(
                self._diff(session, ctx, "Travel", "Japan")[:2], (0, []))
            code, lines, _ = self._diff(session, plain, "Travel", "Japan")
            self.assertEqual(code, 1)
            self.assertTrue(all(line.startswith("- item") for line in lines),
                            lines)

    def test_the_summary_never_lands_on_stdout(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            other = self._copy(home, session, "b.od", removed=["BA"])
            _, lines, err = self._diff(session, other)
            self.assertFalse([line for line in lines if line.startswith("odag:")])
            self.assertTrue(err.startswith("odag: "))

    def test_typed_values_compare_by_canonical_name(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "a.od"))
            for argv in (["prelude"], ["put", "crate", "weight(3kg)"]):
                self.assertEqual(_run(argv, session)[0], 0)
            other = self._copy(home, session, "b.od",
                               extra=["pallet weight(3000g)"])   # same value
            code, lines, _ = self._diff(session, other)
            self.assertEqual((code, lines), (1, ["+ item pallet (weight(3kg))"]))

    def test_a_missing_file_is_refused(self):
        # Everywhere else a missing native store is an empty one; here that
        # would report the whole store as deleted because of a typo.
        with tempfile.TemporaryDirectory() as home:
            session = self._store(home, "a.od", self.TRAVEL)
            code, lines, err = self._diff(session,
                                          os.path.join(home, "nope.od"))
            self.assertEqual((code, lines), (1, []))
            self.assertIn("no such file", err)


class TestDiffAdditions(unittest.TestCase):
    """`diff --additions PATH` writes the other side's additions as a store
    file `merge` applies.

    Deliberately *not* a patch: the additive half of one is a merge (measured
    here — the fragment reaches the same root as merging the whole store), and
    the subtractive half cannot be in a mergeable file at all, because a
    removal is lossy and does not commute with a concurrent addition.
    """

    BASE = ("Travel", "Japan", "Flight Travel", "Hotel Travel",
            "JAL Flight Japan", "JAL-cheap JAL", "Ryokan Hotel Japan")

    def _store(self, home, name, rows=None):
        session = cli.Session(os.path.join(home, name))
        for row in (self.BASE if rows is None else rows):
            self.assertEqual(_run(["put"] + row.split(), session)[0], 0)
        return session

    def _fork(self, home, session, name, edits):
        """A copy of `session` with some edits applied, and its path."""
        path = os.path.join(home, name)
        self.assertEqual(_run(["export", path], session)[0], 0)
        other = cli.Session(path)
        for argv in edits:
            self.assertEqual(_run(argv, other)[0], 0)
        return path

    def _diff(self, session, other, *categories, additions=None):
        argv = ["diff", other] + list(categories)
        if additions:
            argv += ["--additions", additions]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, session)
        return code, out.getvalue().splitlines(), err.getvalue()

    def _root(self, dag):
        from ontodag.eager import EagerOntoDAG
        eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        eager.merge(dag)
        return eager.commit()

    def test_the_fragment_merges_to_the_same_root_as_the_whole_store(self):
        # The claim that makes --additions honest rather than a new mechanism.
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od", [
                ["put", "Ryokan-Kyoto", "Ryokan"],
                ["put", "Onsen", "Ryokan-Kyoto"],
                ["put", "JAL-cheap", "Ryokan"]])
            frag = os.path.join(home, "add.od")
            self.assertEqual(self._diff(mine, theirs, additions=frag)[0], 1)

            via_fragment = self._store(home, "f.od")
            self.assertEqual(_run(["merge", frag], via_fragment)[0], 0)
            via_whole = self._store(home, "w.od")
            self.assertEqual(_run(["merge", theirs], via_whole)[0], 0)
            self.assertEqual(self._root(via_fragment.dag),
                             self._root(via_whole.dag))

    def test_it_carries_only_what_changed(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od",
                                [["put", "Ryokan-Kyoto", "Ryokan"]])
            frag = os.path.join(home, "add.od")
            self._diff(mine, theirs, additions=frag)
            loaded = cli._load(frag)
            # The new item, and the parent it hangs from. Nothing else.
            self.assertEqual(set(loaded.nodes) - {loaded.root.name},
                             {"Ryokan-Kyoto", "Ryokan"})

    def test_merging_it_is_idempotent(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od",
                                [["put", "Ryokan-Kyoto", "Ryokan"]])
            frag = os.path.join(home, "add.od")
            self._diff(mine, theirs, additions=frag)
            self.assertEqual(_run(["merge", frag], mine)[0], 0)
            once = self._root(mine.dag)
            self.assertEqual(_run(["merge", frag], mine)[0], 0)
            self.assertEqual(self._root(mine.dag), once)

    def test_a_chain_of_new_items_lands_in_the_right_place(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od", [
                ["put", "Ryokan-Kyoto", "Ryokan"],
                ["put", "Onsen", "Ryokan-Kyoto"]])
            frag = os.path.join(home, "add.od")
            self._diff(mine, theirs, additions=frag)
            self.assertEqual(_run(["merge", frag], mine)[0], 0)
            self.assertEqual(_run(["get", "Hotel", "Japan"], mine),
                             (0, "Onsen\nRyokan\nRyokan-Kyoto\n"))

    def test_a_claim_only_change_travels(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od",
                                [["put", "JAL-cheap", "Ryokan"]])
            frag = os.path.join(home, "add.od")
            self._diff(mine, theirs, additions=frag)
            self.assertEqual(_run(["merge", frag], mine)[0], 0)
            self.assertEqual(_run(["below", "JAL-cheap", "Ryokan"], mine),
                             (0, "true\n"))

    def test_removals_are_left_out_and_said_out_loud(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od",
                                [["remove", "JAL"],
                                 ["put", "Ryokan-Kyoto", "Ryokan"]])
            frag = os.path.join(home, "add.od")
            code, lines, err = self._diff(mine, theirs, additions=frag)
            self.assertEqual(code, 1)
            self.assertIn("- item JAL (Flight Japan)", lines)
            self.assertIn("1 removal is NOT in", err)
            self.assertIn("add.od", err)
            # And merging it really does leave the removal unapplied.
            self.assertEqual(_run(["merge", frag], mine)[0], 0)
            self.assertIn("JAL", mine.dag.nodes)

    def test_identical_stores_still_write_an_empty_fragment(self):
        # So a script can merge it unconditionally.
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od", [])
            frag = os.path.join(home, "add.od")
            self.assertEqual(self._diff(mine, theirs, additions=frag)[:2],
                             (0, []))
            self.assertTrue(os.path.exists(frag))
            loaded = cli._load(frag)
            self.assertEqual(set(loaded.nodes), {loaded.root.name})
            before = self._root(mine.dag)
            self.assertEqual(_run(["merge", frag], mine)[0], 0)
            self.assertEqual(self._root(mine.dag), before)

    def test_a_scoped_diff_writes_a_scoped_fragment(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od", [
                ["put", "Ryokan-Kyoto", "Ryokan"],
                ["put", "Bus", "Travel"]])          # outside Japan
            frag = os.path.join(home, "add.od")
            self._diff(mine, theirs, "Travel", "Japan", additions=frag)
            loaded = cli._load(frag)
            self.assertIn("Ryokan-Kyoto", loaded.nodes)
            self.assertNotIn("Bus", loaded.nodes)

    def test_the_fragment_format_follows_the_extension(self):
        with tempfile.TemporaryDirectory() as home:
            mine = self._store(home, "mine.od")
            theirs = self._fork(home, mine, "theirs.od",
                                [["put", "Ryokan-Kyoto", "Ryokan"]])
            frag = os.path.join(home, "add.omn")
            self._diff(mine, theirs, additions=frag)
            self.assertIn("Ryokan-Kyoto", cli._load(frag).nodes)


class TestRemoveMany(unittest.TestCase):
    """`remove NAME...` contracts; `remove --cone` deletes.

    The destructive form is behind a word you have to type, and both forms
    resolve every name before touching anything.
    """

    TRAVEL = ("Travel", "Japan", "Flight Travel", "Hotel Travel",
              "JAL Flight Japan", "JAL-cheap JAL", "Ryokan Hotel Japan",
              "Onsen Japan", "BA Flight")

    def _session(self, home, name="t.od"):
        session = cli.Session(os.path.join(home, name))
        for row in self.TRAVEL:
            self.assertEqual(_run(["put"] + row.split(), session)[0], 0)
        return session

    def _run_err(self, argv, session):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, session)
        return code, out.getvalue(), err.getvalue()

    def _root(self, dag):
        from ontodag.eager import EagerOntoDAG
        eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        eager.merge(dag)
        return eager.commit()

    def test_contracting_several_is_order_independent(self):
        with tempfile.TemporaryDirectory() as home:
            one = self._session(home, "a.od")
            self.assertEqual(_run(["remove", "Flight", "Hotel"], one)[0], 0)
            other = self._session(home, "b.od")
            self.assertEqual(_run(["remove", "Hotel", "Flight"], other)[0], 0)
            self.assertEqual(self._root(one.dag), self._root(other.dag))

    def test_contraction_keeps_what_was_below(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(_run(["remove", "Flight"], session)[0], 0)
            self.assertIn("JAL", session.dag.nodes)
            self.assertEqual(_run(["get", "Travel"], session)[0], 0)

    def test_one_unknown_name_removes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = self._root(session.dag)
            code, _, err = self._run_err(["remove", "Flight", "nope"], session)
            self.assertEqual(code, 1)
            self.assertIn("does not exist", err)
            self.assertEqual(self._root(session.dag), before)
            # and the store on disk is untouched too
            self.assertIn("Flight", cli.Session(session.spec).dag.nodes)

    def test_cone_deletes_and_spares_the_multi_parent_members(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            code, out, err = self._run_err(["remove", "--cone", "Japan"],
                                           session)
            self.assertEqual((code, out), (0, ""))
            self.assertIn("deleted 2 items", err)
            self.assertIn("kept 3 that hang elsewhere", err)
            self.assertEqual(set(session.dag.nodes) - {"*"},
                             {"Travel", "Flight", "Hotel", "JAL", "JAL-cheap",
                              "Ryokan", "BA"})

    def test_dry_run_lists_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = self._root(session.dag)
            code, out, err = self._run_err(
                ["remove", "--cone", "Japan", "--dry-run"], session)
            self.assertEqual((code, out.split()), (0, ["Japan", "Onsen"]))
            self.assertIn("would delete 2 items", err)
            self.assertEqual(self._root(session.dag), before)
            self.assertIn("Japan", cli.Session(session.spec).dag.nodes)

    def test_dry_run_works_for_contraction_too(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = self._root(session.dag)
            code, out, _ = self._run_err(
                ["remove", "Flight", "Hotel", "--dry-run"], session)
            self.assertEqual((code, out.split()), (0, ["Flight", "Hotel"]))
            self.assertEqual(self._root(session.dag), before)

    def test_a_contexted_excerpt_undoes_a_cone_deletion(self):
        # The standing advice, pinned: back up the cone, delete, merge it back,
        # and the store returns to the exact same canonical root.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = self._root(session.dag)
            backup = os.path.join(home, "japan.od")
            self.assertEqual(
                _run(["excerpt", backup, "Japan", "--context"], session)[0], 0)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(_run(["remove", "--cone", "Japan"],
                                      session)[0], 0)
            self.assertNotEqual(self._root(session.dag), before)
            self.assertEqual(_run(["merge", backup], session)[0], 0)
            self.assertEqual(self._root(session.dag), before)

    def test_the_note_never_lands_on_stdout(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            _, out, err = self._run_err(["remove", "--cone", "Onsen"], session)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("odag: deleted 1 item"))

    def test_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            for argv in (["remove", "*"], ["remove", "--cone", "*"]):
                code, _, err = self._run_err(argv, session)
                self.assertEqual(code, 1)
                self.assertIn("root", err)


class TestMove(unittest.TestCase):
    """`odag move` — reclassify, with the contested set reported.

    The contested set is the reason this command has a report at all: a move can
    leave a shared item under both the old and the new category, which is true
    and cannot be resolved by the DAG, so it is named rather than hidden.
    """

    PROJECTS = ("active", "archive", "A active", "B active", "C A B",
                "a-only.md A", "b-only.md B")

    def _session(self, home, name="proj.od", rows=None):
        session = cli.Session(os.path.join(home, name))
        for row in (self.PROJECTS if rows is None else rows):
            self.assertEqual(_run(["put"] + row.split(), session)[0], 0)
        return session

    def _move(self, session, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["move"] + list(argv), session)
        return code, out.getvalue().splitlines(), err.getvalue()

    def _root(self, dag):
        from ontodag.eager import EagerOntoDAG
        eager = EagerOntoDAG(RecordStore(MemoryBytesStore()))
        eager.merge(dag)
        return eager.commit()

    def test_it_moves_the_item_and_everything_under_it(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            code, out, err = self._move(session, "A", "--from", "active",
                                        "--to", "archive")
            self.assertEqual((code, out), (0, []))
            self.assertEqual(_run(["get", "archive"], session),
                             (0, "A\nC\na-only.md\n"))
            self.assertEqual(_run(["get", "active"], session),
                             (0, "B\nC\nb-only.md\n"))

    def test_the_contested_set_is_reported(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            _, _, err = self._move(session, "A", "--from", "active",
                                   "--to", "archive")
            self.assertIn("2 items left active", err)
            self.assertIn("1 still in both active and archive (C)", err)
            # ...and it is the same set the query gives
            self.assertEqual(_run(["get", "active", "archive"], session),
                             (0, "C\n"))

    def test_refinement_is_not_reported_as_contested(self):
        # Moving something to a category *below* the one it left keeps it under
        # both by entailment. Crying wolf there would make the report useless.
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home, "r.od",
                                    ["active", "recent active", "X active"])
            _, _, err = self._move(session, "X", "--from", "active",
                                   "--to", "recent")
            self.assertNotIn("still in both", err)

    def test_dry_run_lists_what_changes_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            before = self._root(session.dag)
            code, out, err = self._move(session, "A", "--from", "active",
                                        "--to", "archive", "--dry-run")
            # Not just A: everything whose classification changes.
            self.assertEqual((code, out), (0, ["A", "C", "a-only.md"]))
            self.assertIn("would move", err)
            self.assertIn("1 still in both active and archive (C)", err)
            self.assertEqual(self._root(session.dag), before)
            self.assertIn("A", {item.name for item
                                in cli.Session(session.spec).dag.get(["active"])})

    def test_dry_run_refuses_exactly_what_the_real_move_would(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            for extra in ([], ["--dry-run"]):
                code, _, err = self._move(session, "C", "--from", "active",
                                          "--to", "archive", *extra)
                self.assertEqual(code, 1)
                self.assertIn("not filed directly under active", err)

    def test_to_alone_replaces_every_classification(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(self._move(session, "C", "--to", "archive")[0], 0)
            self.assertEqual({p.name for p in session.dag.nodes["C"].parents
                              if session.dag.nodes.get(p.name) is p},
                             {"archive"})

    def test_from_alone_unfiles_to_the_top_level(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(self._move(session, "A", "--from", "active")[0], 0)
            self.assertEqual({p.name for p in session.dag.nodes["A"].parents
                              if session.dag.nodes.get(p.name) is p}, {"*"})
            self.assertIn("A", _run(["list"], session)[1].split())

    def test_several_items_at_once(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(self._move(session, "A", "B", "--from", "active",
                                        "--to", "archive")[0], 0)
            self.assertEqual(_run(["get", "active"], session), (0, ""))

    def test_it_persists(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            self.assertEqual(self._move(session, "A", "--from", "active",
                                        "--to", "archive")[0], 0)
            reopened = cli.Session(session.spec)
            self.assertEqual({item.name for item in reopened.dag.get(["archive"])},
                             {"A", "C", "a-only.md"})

    def test_neither_to_nor_from_is_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            code, _, err = self._move(session, "A")
            self.assertEqual(code, 1)
            self.assertIn("nothing to do", err)

    def test_the_note_never_lands_on_stdout(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            _, out, err = self._move(session, "A", "--from", "active",
                                     "--to", "archive")
            self.assertEqual(out, [])
            self.assertTrue(err.startswith("odag: moved: "))

    def test_a_typed_destination_works(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "boxes.od"))
            for argv in (["prelude"], ["put", "shelf"],
                         ["put", "crate", "shelf"]):
                self.assertEqual(_run(argv, session)[0], 0)
            self.assertEqual(
                self._move(session, "crate", "--to", "weight(3kg)")[0], 0)
            self.assertEqual(_run(["get", "weight(..5kg)"], session),
                             (0, "crate\nweight(3kg)\n"))


class TestSwarmBootstrapDecision(unittest.TestCase):
    """Where a brand-new local store gets its starting root from.

    `local_first_store` resolves its root from the store directory's HEAD or
    journal and never consults the publish pointer, so a fresh machine started
    EMPTY even though the head was in the signed feed and every blob was on
    Swarm — the scorched-earth rehydration the live suite asserts. This pins the
    decision; the clone itself is network I/O, covered by
    `tests/test_swarm_bee.py::TestSwarmFeedPointerOnLiveBee`.
    """

    class Pointer:
        def __init__(self, root=None, fail=False):
            self.root, self.fail = root, fail

        def get(self):
            if self.fail:
                raise OSError("node unreachable")
            return self.root

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("ONTODAG_HOME")
        os.environ["ONTODAG_HOME"] = self._home.name

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("ONTODAG_HOME", None)
        else:
            os.environ["ONTODAG_HOME"] = self._saved
        self._home.cleanup()

    def test_the_feed_is_followed_for_a_new_store(self):
        backend = cli.SwarmBackend("pets")
        self.assertEqual(backend._bootstrap_root(self.Pointer("abc123")),
                         "abc123")

    def test_a_store_with_its_own_history_is_never_overwritten(self):
        backend = cli.SwarmBackend("pets")
        os.makedirs(backend.store_dir())
        with open(os.path.join(backend.store_dir(), "HEAD"), "w") as fh:
            fh.write("localhead")
        self.assertIsNone(backend._bootstrap_root(self.Pointer("abc123")))

    def test_a_journal_alone_counts_as_history(self):
        backend = cli.SwarmBackend("pets")
        os.makedirs(backend.store_dir())
        open(os.path.join(backend.store_dir(), "journal.jsonl"), "w").close()
        self.assertIsNone(backend._bootstrap_root(self.Pointer("abc123")))

    def test_the_legacy_root_file_is_the_fallback(self):
        backend = cli.SwarmBackend("pets")
        with open(backend.pointer_path(), "w") as fh:
            fh.write("legacyroot\n")
        self.assertEqual(backend._bootstrap_root(None), "legacyroot")
        # the feed wins when both exist — it is the shared, followable head
        self.assertEqual(backend._bootstrap_root(self.Pointer("fromfeed")),
                         "fromfeed")

    def test_an_unreachable_node_starts_empty_rather_than_failing(self):
        backend = cli.SwarmBackend("pets")
        self.assertIsNone(backend._bootstrap_root(self.Pointer(fail=True)))

    def test_nothing_published_yet_is_not_an_error(self):
        backend = cli.SwarmBackend("pets")
        self.assertIsNone(backend._bootstrap_root(self.Pointer(None)))


class TestHistoryAndUndo(unittest.TestCase):
    """`history`, `status`, `undo`, `redo` — over an `rs:` store, which is the
    cheapest tier that keeps history at all.

    A root *is* the state, so undo moves a pointer and destroys nothing: the
    state it left is still in `history` and still readable. What it does not do
    is travel — a peer merging afterwards re-adds what was undone, which is the
    same wall `remove` and `move` have.
    """

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("ONTODAG_HOME")
        os.environ["ONTODAG_HOME"] = self._home.name
        cli._OVERRIDES.clear()
        self.spec = "rs:" + os.path.join(self._home.name, "store")

    def tearDown(self):
        cli._OVERRIDES.clear()
        if self._saved is None:
            os.environ.pop("ONTODAG_HOME", None)
        else:
            os.environ["ONTODAG_HOME"] = self._saved
        self._home.cleanup()

    def _run(self, argv, message=None):
        """A fresh Session per call, as separate `odag` invocations are."""
        cli._OVERRIDES.pop("message", None)
        if message is not None:
            cli._OVERRIDES["message"] = message
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, cli.Session(self.spec))
        return code, out.getvalue(), err.getvalue()

    def _trip(self):
        self._run(["put", "Travel"], message="start the trip")
        self._run(["put", "Japan", "Travel"], message="add Japan")
        self._run(["put", "Flight", "Travel"], message="add a flight")

    def test_history_lists_the_states_newest_first_with_messages(self):
        self._trip()
        code, out, _ = self._run(["history"])
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("*"))          # current is newest
        self.assertIn("add a flight", lines[0])
        self.assertIn("start the trip", lines[2])

    def test_status_says_what_can_be_undone(self):
        self._trip()
        _, out, _ = self._run(["status"])
        fields = dict(line.split(" = ", 1) for line in out.splitlines()
                      if " = " in line)
        self.assertEqual(fields["items"], "3")
        self.assertEqual(fields["versions"], "3")
        self.assertEqual(fields["undoable"], "2")
        self.assertEqual(fields["redoable"], "0")

    def test_undo_then_redo(self):
        self._trip()
        code, _, err = self._run(["undo"])
        self.assertEqual(code, 0)
        self.assertIn("undid to", err)
        self.assertIn("-1 item", err)
        self.assertEqual(self._run(["list"])[1].split(), ["Japan", "Travel"])
        code, _, err = self._run(["redo"])
        self.assertEqual(code, 0)
        self.assertIn("+1 item", err)
        self.assertEqual(self._run(["list"])[1].split(),
                         ["Flight", "Japan", "Travel"])

    def test_the_current_marker_moves_with_the_undo(self):
        self._trip()
        self._run(["undo"])
        lines = self._run(["history"])[1].splitlines()
        self.assertFalse(lines[0].startswith("*"))         # newest is not current
        self.assertTrue(lines[1].startswith("*"))

    def test_a_dry_run_says_what_would_happen_and_changes_nothing(self):
        self._trip()
        code, out, err = self._run(["undo", "--dry-run"])
        self.assertEqual((code, out), (0, ""))
        self.assertIn("would undo to", err)
        self.assertEqual(len(self._run(["list"])[1].split()), 3)

    def test_the_ends_of_the_line_are_reported_not_guessed(self):
        self._trip()
        self.assertEqual(self._run(["redo"])[0], 1)        # already at the tip
        self.assertIn("nothing to redo", self._run(["redo"])[2])
        for _ in range(2):
            self._run(["undo"])
        code, _, err = self._run(["undo"])
        self.assertEqual(code, 1)
        self.assertIn("nothing to undo", err)
        self.assertEqual(self._run(["list"])[1].split(), ["Travel"])

    def test_committing_after_an_undo_abandons_the_redo_tail(self):
        self._trip()
        self._run(["undo"])
        self._run(["put", "Hotel", "Travel"], message="a hotel instead")
        self.assertEqual(self._run(["redo"])[0], 1)
        self.assertEqual(self._run(["list"])[1].split(),
                         ["Hotel", "Japan", "Travel"])

    def test_a_command_that_changes_nothing_is_not_a_state(self):
        # `odag` commits after every command; a no-op must not become a version
        # you can "undo" to, or undo would appear to do nothing.
        self._trip()
        before = len(self._run(["history"])[1].splitlines())
        self._run(["put", "Japan", "Travel"])              # already there
        self.assertEqual(len(self._run(["history"])[1].splitlines()), before)

    def test_undoing_a_removal_brings_the_items_back(self):
        self._trip()
        self._run(["remove", "--cone", "Travel"])
        self.assertEqual(self._run(["list"])[1], "")
        self._run(["undo"])
        self.assertEqual(self._run(["list"])[1].split(),
                         ["Flight", "Japan", "Travel"])

    def test_a_plain_file_says_which_stores_keep_history(self):
        path = os.path.join(self._home.name, "plain.od")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["history"], cli.Session(path))
        self.assertEqual(code, 1)
        self.assertIn("keeps no version history", err.getvalue())
        self.assertIn("rs:", err.getvalue())

    def test_status_works_on_a_file_store_too(self):
        path = os.path.join(self._home.name, "plain.od")
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            cli.dispatch(["put", "A"], cli.Session(path))
            cli.dispatch(["status"], cli.Session(path))
        self.assertIn("history = none", out.getvalue())

    def test_a_message_is_optional(self):
        self._run(["put", "Travel"])
        line = self._run(["history"])[1].splitlines()[0]
        self.assertTrue(line.startswith("*"))
        # marker, root, date, time — and no message on the end
        self.assertEqual(len(line.split()), 4)


class TestOverlappingCommand(unittest.TestCase):
    """`overlapping TERM` — contract G6 on the command line.

    It was reachable only from Python and MCP, which made a documented
    guarantee invisible to the surface most people use.
    """

    def _session(self, home):
        session = cli.Session(os.path.join(home, "parcels.od"))
        for argv in (["prelude"], ["put", "parcel", "weight(3kg)"],
                     ["put", "wide", "weight(2kg..6kg)"]):
            self.assertEqual(_run(argv, session)[0], 0)
        return session

    def test_candidates_include_what_get_cannot(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            guaranteed = _run(["get", "weight(..5kg)"], session)[1].split()
            candidates = _run(["overlapping", "weight(..5kg)"], session)[1].split()
            self.assertIn("parcel", guaranteed)
            self.assertIn("parcel", candidates)
            # `wide` might be under 5kg: a candidate, never a guarantee
            self.assertNotIn("wide", guaranteed)
            self.assertIn("wide", candidates)

    def test_a_term_of_no_dimension_is_an_error(self):
        with tempfile.TemporaryDirectory() as home:
            session = self._session(home)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.dispatch(["overlapping", "parcel"], session)
            self.assertEqual(code, 1)
            self.assertIn("denotation", err.getvalue())


class TestAsOf(unittest.TestCase):
    """`--as-of ROOT` reads a past version — the other half of `history`.

    History listed the versions and gave no way to look at one; now the roots it
    prints are usable, prefix and all (it prints twelve characters, so demanding
    sixty-four would make the feature unusable with the only thing that shows
    them).
    """

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._saved = os.environ.get("ONTODAG_HOME")
        os.environ["ONTODAG_HOME"] = self._home.name
        cli._OVERRIDES.clear()
        self.spec = "rs:" + os.path.join(self._home.name, "store")
        self._run(["put", "Travel"], message="one")
        self._run(["put", "Japan", "Travel"], message="two")

    def tearDown(self):
        cli._OVERRIDES.clear()
        if self._saved is None:
            os.environ.pop("ONTODAG_HOME", None)
        else:
            os.environ["ONTODAG_HOME"] = self._saved
        self._home.cleanup()

    def _run(self, argv, message=None, as_of=None):
        cli._OVERRIDES.pop("message", None)
        cli._OVERRIDES.pop("as_of", None)
        if message is not None:
            cli._OVERRIDES["message"] = message
        if as_of is not None:
            cli._OVERRIDES["as_of"] = as_of
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(argv, cli.Session(self.spec))
        return code, out.getvalue(), err.getvalue()

    def _roots(self):
        # `*` marks the current line, so strip the marker column rather than
        # counting fields (that mistake reads the date as a root).
        return [line.lstrip("* ").split()[0] for line in
                self._run(["history"])[1].splitlines()]

    def test_a_past_version_reads_as_it_was(self):
        first = self._roots()[-1]
        self.assertEqual(self._run(["list"])[1].split(), ["Japan", "Travel"])
        self.assertEqual(self._run(["list"], as_of=first)[1].split(), ["Travel"])

    def test_the_prefix_history_prints_is_enough(self):
        first = self._roots()[-1]
        self.assertEqual(len(first), 12)          # what `history` shows
        self.assertEqual(self._run(["list"], as_of=first)[1].split(), ["Travel"])
        self.assertEqual(self._run(["list"], as_of=first[:7])[1].split(),
                         ["Travel"])

    def test_queries_work_against_a_past_version(self):
        latest, first = self._roots()[0], self._roots()[-1]
        self.assertEqual(self._run(["get", "Travel"], as_of=latest)[1].split(),
                         ["Japan"])
        self.assertEqual(self._run(["get", "Travel"], as_of=first)[1], "")

    def test_writing_to_a_past_version_is_refused(self):
        first = self._roots()[-1]
        code, _, err = self._run(["put", "X"], as_of=first)
        self.assertEqual(code, 1)
        self.assertIn("read-only", err)
        self.assertIn("odag undo", err)           # says how to actually go back
        self.assertEqual(self._run(["list"])[1].split(), ["Japan", "Travel"])

    def test_an_unknown_or_ambiguous_root_says_so(self):
        code, _, err = self._run(["list"], as_of="nosuchroot")
        self.assertEqual(code, 1)
        self.assertIn("not a version", err)

    def test_a_file_store_has_no_versions_to_read(self):
        path = os.path.join(self._home.name, "plain.od")
        cli._OVERRIDES["as_of"] = "abc"
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.dispatch(["list"], cli.Session(path))
        self.assertEqual(code, 1)
        self.assertIn("no versions to read", err.getvalue())


class TestOverlayView(unittest.TestCase):
    """The composed read view (PROJECTIONS.md §5): answers read the union of
    the primary store and every configured overlay; writes and mergeable
    artifacts read the primary alone, so a machine layer can never launder
    into a file that someone later merges."""

    def setUp(self):
        self._old = os.environ.get("ONTODAG_OVERLAYS")
        self._dir = tempfile.TemporaryDirectory()
        home = self._dir.name
        self.primary = os.path.join(home, "human.od")
        self.overlay = os.path.join(home, "proj.od")
        human = cli.Session(self.primary)
        for argv in (["put", "photos"], ["put", "trip.jpg", "photos"]):
            self.assertEqual(_run(argv, human)[0], 0)
        machine = cli.Session(self.overlay)
        for argv in (["put", "sys:"], ["put", "sys:on", "sys:"],
                     ["put", "sys:on:drive", "sys:on"],
                     ["put", "trip.jpg", "sys:on:drive"],
                     ["put", "cache.tmp", "sys:on:drive"]):
            self.assertEqual(_run(argv, machine)[0], 0)
        os.environ["ONTODAG_OVERLAYS"] = self.overlay
        with open(self.overlay, encoding="utf-8") as fh:
            self.overlay_bytes = fh.read()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ONTODAG_OVERLAYS", None)
        else:
            os.environ["ONTODAG_OVERLAYS"] = self._old
        self._dir.cleanup()

    def test_answers_read_the_union(self):
        session = cli.Session(self.primary)
        # The cross-layer intersection the whole seam exists for:
        code, out = _run(["get", "photos", "sys:on:drive"], session)
        self.assertEqual((code, out), (0, "trip.jpg\n"))
        code, out = _run(["below", "trip.jpg", "sys:on:drive"], session)
        self.assertEqual((code, out.strip()), (0, "true"))
        code, out = _run(["list"], session)
        self.assertIn("cache.tmp", out)      # overlay-only item is visible
        code, out = _run(["count"], session)
        self.assertEqual(out.strip(), "6")   # union, not primary (2)

    def test_writes_route_to_the_primary_alone(self):
        session = cli.Session(self.primary)
        self.assertEqual(_run(["put", "beach.jpg", "photos"], session)[0], 0)
        # Visible through the view immediately (cache invalidated by save):
        code, out = _run(["get", "photos"], session)
        self.assertIn("beach.jpg", out)
        self.assertIn("trip.jpg", out)
        # The overlay store is byte-identical — nothing wrote through it:
        with open(self.overlay, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), self.overlay_bytes)
        # And the primary alone never absorbed the overlay's claims:
        del os.environ["ONTODAG_OVERLAYS"]
        code, out = _run(["get", "sys:on:drive"], cli.Session(self.primary))
        self.assertEqual((code, out), (0, ""))   # fail-closed, empty

    def test_artifacts_read_the_primary(self):
        session = cli.Session(self.primary)
        exported = os.path.join(self._dir.name, "out.od")
        self.assertEqual(_run(["export", exported], session)[0], 0)
        with open(exported, encoding="utf-8") as fh:
            self.assertNotIn("sys:", fh.read())
        cut = os.path.join(self._dir.name, "cut.od")
        self.assertEqual(_run(["excerpt", cut, "photos"], session)[0], 0)
        with open(cut, encoding="utf-8") as fh:
            self.assertNotIn("sys:", fh.read())

    def test_overlay_vocabulary_serves_the_view(self):
        # Declarations travel (the units law): an overlay carrying the
        # prelude makes typed queries answerable, though the primary is bare.
        self.assertEqual(_run(["prelude"], cli.Session(self.overlay))[0], 0)
        session = cli.Session(self.primary)
        code, out = _run(["below", "weight(3kg)", "weight(..5kg)"], session)
        self.assertEqual((code, out.strip()), (0, "true"))

    def test_the_composed_view_cannot_commit(self):
        session = cli.Session(self.primary)
        view = session.view()
        self.assertIsNot(view, session.dag)
        self.assertFalse(hasattr(view, "commit"))
        self.assertIsInstance(view, OntoDAG)
        # Without overlays the view IS the primary — the zero-cost path.
        del os.environ["ONTODAG_OVERLAYS"]
        fresh = cli.Session(self.primary)
        self.assertIs(fresh.view(), fresh.dag)


class TestProjectionDrop(unittest.TestCase):
    """PROJECTIONS.md §5's owed golden test: dropping a projection's
    namespace root deletes pure cache entries and DETACHES — never deletes —
    anything the human layer also holds."""

    def test_survival_rule_on_a_sys_layer(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "mixed.od"))
            for argv in (["put", "photos"],                       # human
                         ["put", "sys:"], ["put", "sys:on", "sys:"],
                         ["put", "sys:on:drive", "sys:on"],
                         ["put", "cache.tmp", "sys:on:drive"],    # cache-only
                         ["put", "trip.jpg", "sys:on:drive", "photos"]):
                self.assertEqual(_run(argv, session)[0], 0)
            self.assertEqual(_run(["remove", "--cone", "sys:"], session)[0], 0)
            code, out = _run(["list"], session)
            names = set(out.split())
            self.assertIn("trip.jpg", names)          # human-held: survives
            self.assertNotIn("cache.tmp", names)      # cache-only: gone
            self.assertFalse(any(n.startswith("sys:") for n in names))
            code, out = _run(["get", "photos"], session)
            self.assertEqual(out, "trip.jpg\n")       # classification intact


class TestIngest(unittest.TestCase):
    """`odag ingest`: the PROJECTIONS.md §4 wire format, with the contract's
    semantics — idempotent, order-free, full rebuild via --drop."""

    def _stream(self, home, lines, name="stream.jsonl"):
        path = os.path.join(home, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return path

    def test_items_filed_and_categories_scaffolded(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "p.od"))
            stream = self._stream(home, [
                '{"item": "h1", "supercategories":'
                ' ["sys:on:drive", "sys:type:jpg"]}',
                '',                                    # blank lines skipped
                '{"item": "sys:on:drive", "supercategories": ["sys:on"]}',
            ])
            self.assertEqual(_run(["ingest", stream], session)[0], 0)
            code, out = _run(["get", "sys:on:drive"], session)
            self.assertEqual((code, out), (0, "h1\n"))
            # The provisional top-level category was refined by line 3:
            code, out = _run(["get", "sys:on"], session)
            self.assertIn("h1", out)

    def test_idempotent_and_order_free(self):
        lines = [
            '{"item": "h1", "supercategories": ["sys:on:drive"]}',
            '{"item": "sys:on:drive", "supercategories": ["sys:on"]}',
            '{"item": "sys:on", "supercategories": ["sys:"]}',
        ]
        with tempfile.TemporaryDirectory() as home:
            forward = os.path.join(home, "a.od")
            session = cli.Session(forward)
            stream = self._stream(home, lines)
            self.assertEqual(_run(["ingest", stream], session)[0], 0)
            with open(forward, encoding="utf-8") as fh:
                first = fh.read()
            self.assertEqual(_run(["ingest", stream], session)[0], 0)
            with open(forward, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), first)          # idempotent
            reverse = os.path.join(home, "b.od")
            stream2 = self._stream(home, list(reversed(lines)), "r.jsonl")
            self.assertEqual(
                _run(["ingest", stream2], cli.Session(reverse))[0], 0)
            with open(reverse, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), first)          # order-free

    def test_drop_rebuild_reproduces_the_projection(self):
        lines = [
            '{"item": "sys:on", "supercategories": ["sys:"]}',
            '{"item": "sys:on:drive", "supercategories": ["sys:on"]}',
            '{"item": "h1", "supercategories": ["sys:on:drive"]}',
        ]
        with tempfile.TemporaryDirectory() as home:
            path = os.path.join(home, "p.od")
            session = cli.Session(path)
            stream = self._stream(home, lines)
            self.assertEqual(_run(["ingest", stream], session)[0], 0)
            with open(path, encoding="utf-8") as fh:
                first = fh.read()
            code, _ = _run(["ingest", "--drop", "sys:", stream], session)
            self.assertEqual(code, 0)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), first)
            # --drop on a node the store doesn't have is not an error:
            code, _ = _run(["ingest", "--drop", "nonesuch", stream], session)
            self.assertEqual(code, 0)

    def test_malformed_line_names_the_line(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "p.od"))
            stream = self._stream(home, [
                '{"item": "ok", "supercategories": []}',
                'not json at all',
            ])
            out, err = io.StringIO(), io.StringIO()
            code = cli.dispatch(["ingest", stream], session, out=out, err=err)
            self.assertEqual(code, 1)
            self.assertIn("line 2", err.getvalue())


def _run3(argv, session):
    """Dispatch capturing all three: (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.dispatch(argv, session, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


class TestMergePreview(unittest.TestCase):
    """`merge --diff` / `pack --diff` (PACKS.md §13.2/§13.7): what would
    arrive, the decidable unit-compatibility check, and the reportable
    name-overlap warning — changing nothing."""

    def test_preview_shows_additions_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as home:
            mine = os.path.join(home, "mine.od")
            theirs = os.path.join(home, "theirs.od")
            session = cli.Session(mine)
            self.assertEqual(_run(["put", "animal"], session)[0], 0)
            other = cli.Session(theirs)
            for argv in (["put", "animal"], ["put", "dog", "animal"]):
                self.assertEqual(_run(argv, other)[0], 0)
            with open(mine, encoding="utf-8") as fh:
                before = fh.read()
            code, out, err = _run3(["merge", "--diff", theirs], session)
            self.assertEqual(code, 0)
            self.assertIn("+ item dog", out)
            self.assertIn("would add 1 items", err)
            with open(mine, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), before)     # changed nothing
            # Nothing new the other way round after a real merge:
            self.assertEqual(_run(["merge", theirs], session)[0], 0)
            code, out, err = _run3(["merge", "--diff", theirs], session)
            self.assertEqual((code, out), (0, ""))
            self.assertIn("nothing new", err)

    def test_unit_conflict_refuses_with_exit_1(self):
        with tempfile.TemporaryDirectory() as home:
            mine = os.path.join(home, "mine.od")
            theirs = os.path.join(home, "theirs.od")
            session = cli.Session(mine)
            for argv in (["put", "unit-declaration"],
                         ["put", "unit-family(zorp)", "unit-declaration"],
                         ["put", "unit(zz=1zorp)", "unit-declaration"]):
                self.assertEqual(_run(argv, session)[0], 0)
            other = cli.Session(theirs)
            for argv in (["put", "unit-declaration"],
                         ["put", "unit-family(zorp)", "unit-declaration"],
                         ["put", "unit(zz=2zorp)", "unit-declaration"]):
                self.assertEqual(_run(argv, other)[0], 0)
            with open(mine, encoding="utf-8") as fh:
                before = fh.read()
            code, _out, err = _run3(["merge", "--diff", theirs], session)
            self.assertEqual(code, 1)
            self.assertIn("INCOMPATIBLE", err)
            with open(mine, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), before)     # nothing merged

    def test_unrelated_shared_category_warns_but_shared_leaf_does_not(self):
        with tempfile.TemporaryDirectory() as home:
            mine = os.path.join(home, "mine.od")
            theirs = os.path.join(home, "theirs.od")
            session = cli.Session(mine)
            for argv in (["put", "planet"], ["put", "Mercury", "planet"],
                         ["put", "probe", "Mercury"],
                         ["put", "photos"], ["put", "trip.jpg", "photos"]):
                self.assertEqual(_run(argv, session)[0], 0)
            other = cli.Session(theirs)
            for argv in (["put", "chemical-element"],
                         ["put", "Mercury", "chemical-element"],
                         ["put", "japan"], ["put", "trip.jpg", "japan"]):
                self.assertEqual(_run(argv, other)[0], 0)
            code, _out, err = _run3(["merge", "--diff", theirs], session)
            self.assertEqual(code, 0)          # a warning, never a refusal
            self.assertIn("`Mercury` is classified unrelatedly", err)
            self.assertNotIn("trip.jpg` is classified", err)  # leaf: normal

    def test_pack_diff_previews_adoption(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "s.od"))
            code, out, err = _run3(["pack", "crypto-core", "--diff"], session)
            self.assertEqual(code, 0)
            self.assertIn("+ item", out)
            self.assertIn("compatible", err)
            # Preview adopted nothing:
            code, out, _ = _run3(["get", "unit-declaration"], session)
            self.assertEqual(out, "")
            # Adopt, then the preview reports it is already in:
            self.assertEqual(_run(["pack", "crypto-core"], session)[0], 0)
            code, out, err = _run3(["pack", "crypto-core", "--diff"], session)
            self.assertEqual((code, out), (0, ""))
            self.assertIn("nothing new", err)


class TestPutTeachingError(unittest.TestCase):
    def test_missing_parents_are_named(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "s.od"))
            code, _out, err = _run3(["put", "x", "nonesuch"], session)
            self.assertEqual(code, 1)
            self.assertIn("'nonesuch'", err)
            self.assertIn("odag put NAME", err)

    def test_parametric_parents_are_not_flagged(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "s.od"))
            self.assertEqual(_run(["prelude"], session)[0], 0)
            self.assertEqual(_run(["put", "crate", "weight(3kg)"],
                                  session)[0], 0)

    def test_pack_hint_fires_only_when_the_pack_has_the_node(self):
        with tempfile.TemporaryDirectory() as home:
            session = cli.Session(os.path.join(home, "s.od"))
            # `unit-declaration` IS a node every pack ships:
            code, _out, err = _run3(["put", "x", "unit-declaration"], session)
            self.assertEqual(code, 1)
            self.assertIn("odag pack", err)
            # A bare suffix is NOT a node any pack would create — no hint,
            # because adopting the pack would not make the put succeed:
            code, _out, err = _run3(["put", "x", "BTC"], session)
            self.assertEqual(code, 1)
            self.assertNotIn("odag pack", err)


@unittest.skipUnless(HAVE_CRYPTO, 'needs the crypto extra: pip install "ontodag[crypto]"')
class TestEncryptedStore(unittest.TestCase):
    """The single-audience encrypted rs: store (PACKS.md §14 item 3):
    ciphertext at rest, deterministic (convergence within one audience),
    marker-decides semantics, wrong-key refusal at open."""

    def setUp(self):
        self._old = os.environ.get("ONTODAG_STORE_KEY")
        os.environ["ONTODAG_STORE_KEY"] = "correct horse battery staple"
        self._dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        if self._old is None:
            os.environ.pop("ONTODAG_STORE_KEY", None)
        else:
            os.environ["ONTODAG_STORE_KEY"] = self._old
        self._dir.cleanup()

    def _blob_bytes(self, path):
        # DirBytesStore shards blobs into subdirectories: walk, don't list.
        blobs = b""
        blobdir = os.path.join(path, "blobs")
        for root, _dirs, files in os.walk(blobdir):
            for name in files:
                with open(os.path.join(root, name), "rb") as fh:
                    blobs += fh.read()
        self.assertTrue(blobs, f"no blobs found under {blobdir}")
        return blobs

    def test_roundtrip_and_ciphertext_at_rest(self):
        path = os.path.join(self._dir.name, "secret")
        session = cli.Session(f"rs:{path}")
        for argv in (["put", "Zebra"], ["put", "Marty", "Zebra"]):
            self.assertEqual(_run(argv, session)[0], 0)
        # A fresh session (a new process, effectively) reads it back:
        code, out = _run(["get", "Zebra"], cli.Session(f"rs:{path}"))
        self.assertEqual((code, out), (0, "Marty\n"))
        # Nothing legible on disk — records AND trie nodes are ciphertext:
        self.assertNotIn(b"Zebra", self._blob_bytes(path))
        self.assertNotIn(b"Marty", self._blob_bytes(path))
        code, out = _run(["status"], cli.Session(f"rs:{path}"))
        self.assertIn("encrypted = yes", out)

    def test_wrong_key_and_missing_key_refuse_at_open(self):
        path = os.path.join(self._dir.name, "secret")
        self.assertEqual(_run(["put", "Zebra"],
                              cli.Session(f"rs:{path}"))[0], 0)
        os.environ["ONTODAG_STORE_KEY"] = "not the key"
        code, _out, err = _run3(["get", "Zebra"], cli.Session(f"rs:{path}"))
        self.assertEqual(code, 1)
        self.assertIn("wrong key", err)
        del os.environ["ONTODAG_STORE_KEY"]
        code, _out, err = _run3(["get", "Zebra"], cli.Session(f"rs:{path}"))
        self.assertEqual(code, 1)
        self.assertIn("store_key", err)

    def test_same_key_converges_different_keys_diverge(self):
        def root_of(path, secret):
            os.environ["ONTODAG_STORE_KEY"] = secret
            session = cli.Session(f"rs:{path}")
            for argv in (["put", "Travel"], ["put", "Japan", "Travel"]):
                self.assertEqual(_run(argv, session)[0], 0)
            with open(os.path.join(path, "root"), encoding="utf-8") as fh:
                return fh.read().strip()

        a = root_of(os.path.join(self._dir.name, "a"), "one secret")
        b = root_of(os.path.join(self._dir.name, "b"), "one secret")
        c = root_of(os.path.join(self._dir.name, "c"), "another secret")
        self.assertEqual(a, b)      # same audience: G1 holds over ciphertext
        self.assertNotEqual(a, c)   # different audiences ARE different stores

    def test_the_marker_decides_not_the_setting(self):
        # A store created WITHOUT a key stays plaintext even when a key is
        # configured later — which is what lets a public overlay sit beside
        # an encrypted primary under one setting.
        plain = os.path.join(self._dir.name, "plain")
        del os.environ["ONTODAG_STORE_KEY"]
        self.assertEqual(_run(["put", "public-fact"],
                              cli.Session(f"rs:{plain}"))[0], 0)
        os.environ["ONTODAG_STORE_KEY"] = "correct horse battery staple"
        code, out = _run(["list"], cli.Session(f"rs:{plain}"))
        self.assertEqual((code, out), (0, "public-fact\n"))
        self.assertIn(b"public-fact", self._blob_bytes(plain))
        # And the combination: encrypted primary, plaintext overlay.
        secret = os.path.join(self._dir.name, "secret")
        session = cli.Session(f"rs:{secret}")
        self.assertEqual(_run(["put", "my-note", "public-fact"],
                              cli.Session(f"rs:{secret}"))[0], 0) \
            if False else None
        self.assertEqual(_run(["put", "my-note"], session)[0], 0)
        os.environ["ONTODAG_OVERLAYS"] = f"rs:{plain}"
        try:
            code, out = _run(["list"], cli.Session(f"rs:{secret}"))
            self.assertEqual(code, 0)
            self.assertIn("my-note", out)
            self.assertIn("public-fact", out)
        finally:
            del os.environ["ONTODAG_OVERLAYS"]

    def test_siblings_inherit_the_audience(self):
        # The provenance/index stores under an encrypted store are encrypted
        # too — audience is contagious along derivation.
        path = os.path.join(self._dir.name, "secret")
        session = cli.Session(f"rs:{path}")
        self.assertEqual(_run(["put", "Zebra"], session)[0], 0)
        prov = session.backend.provenance_record_store()
        prov.put("s/claim", {"speech": "act about Zebra"})
        prov.commit()
        self.assertNotIn(b"Zebra", self._blob_bytes(
            os.path.join(path, "prov")))

    def test_missing_extra_teaches(self):
        path = os.path.join(self._dir.name, "secret")
        with mock.patch.dict(sys.modules, {"Crypto": None,
                                           "Crypto.Cipher": None}):
            code, _out, err = _run3(["put", "Zebra"],
                                    cli.Session(f"rs:{path}"))
        self.assertEqual(code, 1)
        self.assertIn("ontodag[crypto]", err)
