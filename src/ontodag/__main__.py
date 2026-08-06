"""odag — a Unix-style command line for OntoDAG.

(The command is `odag`, not `od`: `od` is the standard octal-dump utility.)

Design goals (see the module docstring history in CLAUDE.md):
  * silent on success, errors on stderr with a non-zero exit code;
  * a persistent default store in ~/.ontodag so `odag put cat` / `odag get cat`
    work with no file argument;
  * stdin / stdout / pipes: `odag` with no command reads commands from a pipe,
    or drops into an interactive prompt on a tty;
  * `-o FILE` redirects query output; `-f STORE` picks the store for one run;
  * `set store PATH` changes the persistent default.

The core (`ontodag.dag`) has no heavy dependencies, so the common native-store
path imports nothing else; OWL/Manchester support and the visualizer are
imported lazily only when a command actually needs them.
"""

import argparse
import collections
import importlib.util
import errno
import json
import os
import shlex
import socket
import sys
import time

from ontodag.dag import OntoDAG, Item
from ontodag import surface as _surface
from ontodag.dimensions import REGISTRY_VERSION

try:
    from importlib.metadata import version, PackageNotFoundError
    try:
        __version__ = version("ontodag")
    except PackageNotFoundError:
        __version__ = "0.1.0"
except Exception:  # pragma: no cover - importlib.metadata always present on 3.8+
    __version__ = "0.1.0"


# --------------------------------------------------------------------------- #
# Stream encoding
# --------------------------------------------------------------------------- #

def _force_utf8_streams():
    """Make the standard streams UTF-8, matching the store's own encoding.

    On Windows a *console* stdout is written through WriteConsoleW, so a term
    like `árvíztűrő tükörfúrógép` appears correctly on screen — but the moment
    stdout is a file or a pipe, Python falls back to the locale codepage and
    the same term comes out mangled (`odag get dokumentum > out.txt`). The
    store is read and written as UTF-8 unconditionally, so the streams should
    agree with it rather than with whatever codepage the console happens to
    have. No-op on POSIX, where UTF-8 is already the default.

    Only real file objects have `reconfigure`; under `redirect_stdout` a test
    may have substituted a StringIO, which has no encoding to fix.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        current = (getattr(stream, "encoding", None) or "").lower()
        if current.replace("-", "").replace("_", "") == "utf8":
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


# --------------------------------------------------------------------------- #
# Home directory, config and store resolution
# --------------------------------------------------------------------------- #

def _home_dir():
    return os.environ.get("ONTODAG_HOME") or os.path.join(
        os.path.expanduser("~"), ".ontodag"
    )


def _config_path():
    return os.path.join(_home_dir(), "config")


def _read_config():
    cfg = {}
    path = _config_path()
    if not os.path.exists(path):
        return cfg
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            cfg[key.strip()] = value.strip()
    return cfg


def _write_config(cfg):
    """Write the config file, readable only by its owner.

    It can hold `bee_signer` — a private key that can publish to your feed —
    and was previously written with default permissions, which under a typical
    umask left a key group- and world-readable. O_CREAT's mode covers a file
    this call creates; the explicit chmod also repairs one written before this
    (or by an older version), which is the case that actually matters since
    the leak is already on disk by then."""
    os.makedirs(_home_dir(), mode=0o700, exist_ok=True)
    path = _config_path()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for key in sorted(cfg):
            fh.write(f"{key} = {cfg[key]}\n")
    os.chmod(path, 0o600)


def _abspath(path):
    return os.path.abspath(os.path.expanduser(path))


def _is_swarm(spec):
    return spec.startswith("swarm:")


def _is_record_store(spec):
    """`rs:PATH` — a content-addressed record store on local disk."""
    return spec.startswith("rs:")


def _normalize_spec(spec):
    """A store spec is either a `swarm:NAME` URI or a filesystem path.

    Swarm specs are kept verbatim; file paths are made absolute so a spec
    saved to config resolves the same from any working directory, and an
    `rs:` path is absolutised inside its prefix for the same reason."""
    if _is_swarm(spec):
        return spec
    if _is_record_store(spec):
        return "rs:" + _abspath(spec[len("rs:"):])
    return _abspath(spec)


def _default_store_path():
    """The zero-dependency default store: a native text file under the home
    dir. Named separately from `_resolve_store` because error messages offer
    it as the fallback when a configured Swarm store can't be opened."""
    return os.path.join(_home_dir(), "store.od")


# --------------------------------------------------------------------------- #
# Settings: one table, one precedence rule
# --------------------------------------------------------------------------- #
#
# Every setting is settable four ways and resolved the same way:
#
#     command-line flag  >  environment variable  >  config file  >  default
#
# The first two are per-invocation; the config file (written by `set`) is the
# durable one. `auto` is a real value, not a missing one: it means "decide from
# whether output is a terminal", which is what makes `odag get | odag put`
# round-trip while an interactive session stays readable.

# `secret` marks a value that must not be printed back: `odag set` is the
# routine "what is configured?" command, so anything it echoes lands in
# scrollback, screen shares and captured terminal output.
_Setting = collections.namedtuple("_Setting", "env default flag doc secret")
_Setting.__new__.__defaults__ = (False,)

_SETTINGS = {
    "store": _Setting(
        "ONTODAG_STORE", "", "-f PATH",
        "active store: a file path or a swarm:NAME URI"),
    "bee_api": _Setting(
        "BEE_API", "http://localhost:1633", "--bee-api URL",
        "Bee node API endpoint, for swarm: stores"),
    "bee_batch": _Setting(
        "BEE_BATCH", "", "--bee-batch ID",
        "postage batch to pay for Swarm writes"),
    "bee_signer": _Setting(
        "BEE_SIGNER", "", "--bee-signer KEY",
        "private key; when set, the latest root lives in a signed feed",
        secret=True),
    "render": _Setting(
        "ONTODAG_SURFACE", "auto", "--render / --raw",
        "readable output (auto = on at a terminal, off in a pipe)"),
    "limit": _Setting(
        "ONTODAG_LIMIT", "auto", "-n N",
        "max result lines (auto = 50 at a terminal, all in a pipe; 0 = all)"),
}

# Settings given as flags on this invocation. Global flags are recorded here by
# main(); per-command flags stay on `args` and outrank these (the closer the
# flag is to the command, the more specific the intent).
_OVERRIDES = {}


def _configured(key, flag=None):
    """The configured value of a setting, by the one precedence rule above.

    `flag` is a per-command flag value, or None if the command has none.
    Empty strings count as unset, so `BEE_BATCH=` does not shadow config."""
    if flag:
        return flag
    if _OVERRIDES.get(key):
        return _OVERRIDES[key]
    env = os.environ.get(_SETTINGS[key].env)
    if env:
        return env
    cfg = _read_config()
    if cfg.get(key):
        return cfg[key]
    return _SETTINGS[key].default


def _resolve_store(override=None):
    """The active store spec. `store`'s only peculiarity is that its default
    is computed (a path under the home dir) rather than a constant."""
    spec = _configured("store", override)
    return _normalize_spec(spec) if spec else _default_store_path()


# --------------------------------------------------------------------------- #
# Serialization: native line format by default, OWL/Manchester by extension
# --------------------------------------------------------------------------- #

def _detect_format(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".omn":
        return "manchester"
    if ext == ".owl":
        return "owl"
    return "native"


# Node metadata rides on a comment line, which is what makes the extension
# safe in both directions. Readers released before it existed skip every line
# starting with `#`, so they read a metadata-bearing file exactly as they read
# one without: edges only, nothing corrupted. Putting the annotation on the
# node's own line instead — `name parent1 | {...}` — would have every existing
# reader take the JSON for a list of parent names and invent nodes from it.
# The file therefore stays a valid v1 store and the header does not move: the
# edge grammar is unchanged, and metadata is optional enrichment.
_META_LINE = "#:meta"


def _load_native(path):
    """Read the native store: one line per node, `name parent1 parent2 ...`,
    plus a `#:meta <name> <json>` line for each node carrying metadata.

    A missing file is an empty DAG (the default store need not exist yet).
    The format is canonical (nodes, parents and metadata keys sorted on save)
    and the graph is rebuilt via add_edge, so even a hand-edited, non-reduced
    file loads as its unique transitive reduction.
    """
    dag = OntoDAG()
    if not os.path.exists(path):
        return dag
    edges = []
    metadata = {}
    with open(path, encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            if line.startswith(_META_LINE):
                # Strict on purpose: dropping an unreadable annotation is the
                # silent data loss this line type exists to end.
                try:
                    _, name, blob = shlex.split(line)
                    metadata[name] = json.loads(blob)
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"{path}:{number}: malformed {_META_LINE} line ({exc})"
                    ) from exc
                continue
            if line.startswith("#"):
                continue
            tokens = shlex.split(line)
            name = tokens[0]
            if name not in dag.nodes:
                dag.add_node(Item(name))
            for parent in tokens[1:]:
                if parent not in dag.nodes:
                    dag.add_node(Item(parent))
                edges.append((parent, name))
    for parent, child in edges:
        dag.add_edge(dag.nodes[parent], dag.nodes[child])
    for name, values in metadata.items():
        node = dag.nodes.get(name)
        if node is not None:          # an annotation for a node with no edges
            node.metadata.update(values)
    return dag


def _save_native(dag, path):
    lines = ["# ontodag store v1"]
    for name in sorted(dag.nodes):
        if name == dag.root.name:
            continue
        node = dag.nodes[name]
        if node.metadata:
            # sort_keys so the file is byte-stable; json escapes newlines, so
            # the token cannot break the line-oriented parse whatever a label
            # contains.
            blob = json.dumps(node.metadata, sort_keys=True, ensure_ascii=False)
            lines.append(f"{_META_LINE} {shlex.quote(name)} {shlex.quote(blob)}")
        parents = sorted(
            p.name for p in node.parents if dag.nodes.get(p.name) is p
        )
        lines.append(" ".join(shlex.quote(t) for t in [name] + parents))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def _load(path):
    fmt = _detect_format(path)
    if fmt == "native":
        return _load_native(path)
    from ontodag.owl import OWLOntology
    if fmt == "manchester":
        return OWLOntology.import_dag_manchester(file_name=path)
    return OWLOntology(f"file://{_abspath(path)}").import_dag(file_name=path)


def _save(dag, path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fmt = _detect_format(path)
    if fmt == "native":
        _save_native(dag, path)
        return
    from ontodag.owl import OWLOntology
    if fmt == "manchester":
        OWLOntology.export_dag_manchester(dag, path)
    else:
        OWLOntology.export_dag(dag, path)


# --------------------------------------------------------------------------- #
# Storage backends
#
# A backend hides *where* the store lives behind load()/save(dag)/describe().
# The default is a local file (native/OWL/Manchester by extension). A
# `swarm:NAME` spec persists through EagerOntoDAG over a **local-first**
# record store (recordstore[local-first-swarm], 0.19+): commits land in a
# store directory under ~/.ontodag instantly — offline is the normal mode —
# and a background syncer pushes them to Swarm and confirms peer-to-peer.
#
# The store is opened in TRANSIENT WINDOWS, never held: the local-first
# store carries a single-writer lock, and the hydrated in-memory DAG is
# what actually serves a session, so load() opens-hydrates-closes and
# save() opens-commits-syncs-closes (rebinding dag.store for the window).
# Between windows no lock is held — odag, odag-fs mounts, and the MCP
# server interleave freely; simultaneous windows retry briefly on
# StoreLocked. Committing onto a head another writer moved is a clean
# record-level rebase: EagerOntoDAG stages only records changed since its
# own hydrate, so the other writer's untouched records survive (per-record
# last-write-wins on true conflicts). save()'s best-effort sync barrier
# gets the commit onto the network before a short-lived CLI run exits;
# when the node is down the commit is safe locally and the next window's
# syncer picks it up. Two modes:
#
#   with a signer  -> additionally publishes the head to a Swarm feed —
#                     and only after network confirmation, so the feed
#                     never points readers at content the network cannot
#                     serve yet (publish_pointer=SwarmFeedPointer).
#   without one    -> nothing publishable; the head lives in the store
#                     directory's HEAD file. (Pre-local-first stores kept
#                     it in NAME.root — migrated on first open.)
#
# recordstore and the adapter are imported lazily here, so `import ontodag`
# and the native path stay dependency-free (tests/test_boundaries.py B1).
# --------------------------------------------------------------------------- #

#: How long save() waits for the background syncer to confirm the commit
#: on Swarm before letting the process move on (the commit is durable
#: locally either way; tests shrink this).
_SYNC_TIMEOUT = 60
#: How long to retry when another transient window briefly holds the
#: store's writer lock.
_LOCK_RETRY = 5.0


class FileBackend:
    def __init__(self, path):
        self.path = path

    def load(self):
        return _load(self.path)

    def save(self, dag):
        _save(dag, self.path)

    def describe(self):
        return self.path


_UNREACHABLE_ERRNOS = {
    errno.ECONNREFUSED, errno.EHOSTUNREACH, errno.ENETUNREACH,
    errno.ENETDOWN, errno.ETIMEDOUT,
}

# Connection failures reach us wrapped by whichever HTTP client ran: `requests`
# for the blob store, or aiohttp under swarmfs's postage-stamp selection. Both
# subclass OSError but neither subclasses the builtin ConnectionError, so match
# the cause chain (which does bottom out in a real ConnectionRefusedError) and
# fall back to type names for clients that break the chain.
_UNREACHABLE_NAMES = {
    "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
    "ClientConnectorError", "ServerTimeoutError", "MaxRetryError",
    "NewConnectionError",
}


def _is_unreachable(exc):
    """True when `exc` means "no answer from the node", as opposed to the node
    answering with an error (no usable stamp, HTTP 4xx, bad reference)."""
    for _ in range(10):  # bounded: cause chains can be cyclic
        if exc is None:
            return False
        if isinstance(exc, (ConnectionError, socket.gaierror, TimeoutError)):
            return True
        if getattr(exc, "errno", None) in _UNREACHABLE_ERRNOS:
            return True
        if type(exc).__name__ in _UNREACHABLE_NAMES:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def _swarm_open_error(name, api, exc):
    """A ValueError whose message tells the user what to do next.

    Deliberately *not* a silent fallback to the local store: writing to a
    different store than the configured one would let a local file and the
    Swarm store diverge with no signal about which is authoritative. Offer
    the fallback, never take it unasked. Starting the node is likewise the
    user's call — a query command must not spawn a syncing daemon.
    """
    local = _default_store_path()
    if _is_unreachable(exc):
        head = (f"cannot reach the Bee node at {api}, needed by store "
                f"'swarm:{name}' ({exc})\n"
                f"  * start your Bee node, then run this again")
    else:
        head = (f"cannot open swarm store '{name}' via {api}: {exc}\n"
                f"  * check the node and its postage batch "
                f"(odag set shows bee_api / bee_batch)")
    return ValueError(
        f"{head}\n"
        f"  * or work locally for one command:  odag -f {local} ...\n"
        f"  * or switch back to local storage:  odag set store {local}\n"
        f"    (local is the default and needs no node: one text file, "
        f"nothing published)"
    )


class SwarmBackend:
    def __init__(self, name, store_factory=None, index_store_factory=None,
                 prov_store_factory=None):
        if not name:
            raise ValueError("swarm store needs a name, e.g. swarm:mydag")
        if os.sep in name or (os.altsep and os.altsep in name) or name == "..":
            raise ValueError(f"invalid swarm store name: {name!r}")
        self.name = name
        # Injection seam: tests pass a factory returning a RecordStore over an
        # in-memory bytes store, exercising the whole wiring without a node.
        self._store_factory = store_factory
        self._index_store_factory = index_store_factory
        self._prov_store_factory = prov_store_factory

    def provenance_record_store(self):
        """The per-writer provenance store (docs/PROVENANCE.md): signed
        speech acts about claims, in a SEPARATE record store under the
        sibling name NAME-prov — beside the knowledge store, never inside
        it, so identical knowledge keeps identical roots whoever asserted
        it. Same wiring as the data store (and as NAME-index)."""
        if self._prov_store_factory is not None:
            return self._prov_store_factory()
        return SwarmBackend(self.name + "-prov")._record_store()

    def index_record_store(self):
        """The SEPARATE record store for published cone summaries (the
        `odag index` command): same wiring as the data store under the
        sibling name NAME-index, so the derived index never touches the
        ontology's own root (docs/DIMENSIONS.md-era purity rule; see
        ontodag.cones)."""
        if self._index_store_factory is not None:
            return self._index_store_factory()
        return SwarmBackend(self.name + "-index")._record_store()

    def pointer_path(self):
        # the pre-local-first head file (<= ontodag 0.14.x); still read once
        # for migration into the store directory's HEAD
        return os.path.join(_home_dir(), self.name + ".root")

    def store_dir(self):
        return os.path.join(_home_dir(), self.name + ".store")

    def _migrate_legacy_root(self):
        """Seed the local-first store's HEAD from the old NAME.root file,
        once: a pre-local-first store had its blobs on Bee and its head in
        NAME.root. Writing HEAD before the first open makes the new store
        resume at that root — reads then heal lazily from Swarm through
        the syncer's fetcher, so the store hydrates itself."""
        head = os.path.join(self.store_dir(), "HEAD")
        if os.path.exists(head):
            return
        try:
            with open(self.pointer_path(), encoding="utf-8") as f:
                legacy = f.read().strip()
        except FileNotFoundError:
            return
        if legacy:
            os.makedirs(self.store_dir(), exist_ok=True)
            with open(head, "w", encoding="utf-8") as f:
                f.write(legacy)

    def _record_store(self):
        # BeeRemote resolves this order itself, but being explicit keeps
        # `describe`/errors honest about which endpoint is in play
        api = _configured("bee_api") or os.environ.get(
            "BEE_API_URL", "http://localhost:1633")
        # "auto" (ask the node for a usable batch) is this call site's default,
        # not the setting's: `set bee_batch` showing "auto" would misreport an
        # unconfigured batch as a configured one.
        batch = _configured("bee_batch") or "auto"
        signer = _configured("bee_signer")
        try:
            if self._store_factory is not None:
                return self._store_factory()
            from recordstore import local_first_store
            os.makedirs(_home_dir(), exist_ok=True)
            self._migrate_legacy_root()
            publish_pointer = None
            if signer:
                from recordstore import SwarmFeedPointer
                publish_pointer = SwarmFeedPointer(
                    api, self.name, signer=signer, postage_batch_id=batch)
            # Transient windows may overlap for a moment (odag saving while
            # an odag-fs mount rehydrates): the writer lock is only ever
            # held briefly, so a short retry absorbs it.
            deadline = time.monotonic() + _LOCK_RETRY
            while True:
                try:
                    return local_first_store(self.store_dir(), api,
                                             stamp=batch,
                                             publish_pointer=publish_pointer)
                except Exception as exc:
                    if type(exc).__name__ != "StoreLocked" or \
                            time.monotonic() > deadline:
                        raise
                    time.sleep(0.2)
        except ImportError as exc:
            missing = exc.name or "swarmfs"
            raise ValueError(
                f"the swarm backend needs an optional dependency that is not "
                f"installed ({missing!r}); install the swarm extra with:  "
                f"pip install \"ontodag[swarm]\"   "
                f"(that covers the local-first store machinery — swarmfs — "
                f"plus `requests` and `swarm-bee` for feed publication)"
            ) from exc
        except OSError as exc:
            raise _swarm_open_error(self.name, api, exc) from exc

    def load(self):
        from ontodag.eager import EagerOntoDAG
        store = self._record_store()
        try:
            # Hydration reads every record, so a node that dies between
            # opening the store and reading it lands here, not above.
            return EagerOntoDAG(store)
        except OSError as exc:
            raise _swarm_open_error(self.name, _configured("bee_api"),
                                    exc) from exc
        finally:
            # transient window: the in-memory DAG serves the session;
            # save() reopens and rebinds. (No-op for factory test stores.)
            close = getattr(store, "close", None)
            if close is not None:
                close()

    def save(self, dag):
        store = self._record_store()  # transient writer window
        try:
            # Multi-writer convergence is MERGE, not locking: if another
            # window moved the head past this dag's own lineage
            # (`base_root`, the root it last hydrated from or committed),
            # fold the moved head in with the commutative, idempotent DAG
            # merge (I7 — the CRDT property) before committing, so
            # same-node concurrent edits union their parents instead of
            # last-write-wins. An unmoved head commits plainly — that keeps
            # replace-shaped flows (`odag import`) superseding rather than
            # merging back what they just replaced. Rebind before syncing:
            # sync() commits through dag.store, and the previous window
            # is closed.
            head = store.root
            dag.store = store
            if head is not None and head != dag.base_root:
                dag.sync(head, bytes_store=store.blobs)
            else:
                dag.commit()  # local, instant, offline-safe
            # Best-effort barrier: a CLI run is short-lived, so give the
            # background syncer a chance to land the commit on Swarm before
            # the window closes. Offline (or slow) is not an error — the
            # commit is durable locally and the next window's syncer
            # resumes it.
            sync = getattr(store, "sync", None)
            if sync is not None:
                try:
                    sync(timeout=_SYNC_TIMEOUT)
                except Exception as exc:  # TimeoutError, node down, ...
                    print(
                        f"note: committed locally; not yet confirmed on "
                        f"Swarm ({exc}). It will sync on the next use of "
                        f"this store.",
                        file=sys.stderr,
                    )
        finally:
            close = getattr(store, "close", None)
            if close is not None:
                close()

    def describe(self):
        return f"swarm:{self.name}"


class LocalRecordBackend:
    """A content-addressed record store on ordinary disk (`rs:PATH`).

    The rung that was missing between a text file and Swarm. The native
    `.od` store persists perfectly well but has no *identity*: a file has no
    name for its contents, no history, and nothing to prove. Everything that
    makes OntoDAG worth distributing — canonical roots (equal knowledge,
    equal root), immutable snapshots, `is_below` certificates, two writers
    converging under `sync` — is a property of the record store, not of
    Swarm.

    Before this, seeing any of that meant first standing up a Bee node,
    funding a wallet and buying a postage batch: the whole infrastructure
    wall in front of the ideas. Here the same semantics run on a directory,
    which makes `swarm:NAME` a backend swap rather than a new concept.

    Layout, self-contained so the store moves by copying one directory:

        PATH/blobs/         content-addressed data blobs
        PATH/root           the latest root
        PATH/index/...      published cone summaries (`odag index`)
        PATH/prov/...       provenance records, if any
    """

    def __init__(self, path, store_factory=None):
        if not path:
            raise ValueError("a local record store needs a path, "
                             "e.g. rs:~/work/travel")
        self.path = _abspath(path)
        self._store_factory = store_factory

    def _store_at(self, directory):
        from ontodag._extras import require
        rs = require("recordstore", "store", "a local record store (rs:)")
        os.makedirs(directory, exist_ok=True)
        return rs.RecordStore(
            rs.DirBytesStore(os.path.join(directory, "blobs")),
            pointer=rs.FilePointer(os.path.join(directory, "root")))

    def _record_store(self):
        if self._store_factory is not None:
            return self._store_factory()
        return self._store_at(self.path)

    def index_record_store(self):
        return self._store_at(os.path.join(self.path, "index"))

    def provenance_record_store(self):
        return self._store_at(os.path.join(self.path, "prov"))

    def load(self):
        from ontodag.eager import EagerOntoDAG
        return EagerOntoDAG(self._record_store())

    def save(self, dag):
        dag.commit()

    def describe(self):
        return f"rs:{self.path}"


def _make_backend(spec):
    if _is_swarm(spec):
        return SwarmBackend(spec[len("swarm:"):])
    if _is_record_store(spec):
        return LocalRecordBackend(spec[len("rs:"):])
    return FileBackend(spec)


# --------------------------------------------------------------------------- #
# The in-memory session (the loaded store)
# --------------------------------------------------------------------------- #

class Session:
    """The store, opened lazily on first use.

    Opening is I/O — for a `swarm:` spec, network I/O — so it belongs to
    the commands that touch the store, where dispatch()'s error contract
    already applies. Commands that never do (`help`, bare `canon`,
    `set KEY VALUE`, `prelude --show`, `swarm`) must work with the node
    down: a user whose node is unreachable and who types `odag help` to
    find the way out has to get help, not the error they came to fix."""

    def __init__(self, spec):
        self.spec = spec
        self._backend = None
        self._dag = None

    def _load(self):
        backend = _make_backend(self.spec)
        dag = backend.load()
        self._backend, self._dag = backend, dag

    @property
    def backend(self):
        if self._backend is None:
            self._load()
        return self._backend

    @property
    def dag(self):
        if self._dag is None:
            self._load()
        return self._dag

    def switch(self, spec):
        # Atomic, and deliberately EAGER: build and load first, assign only
        # once nothing can fail. A store that won't open (node down) must
        # leave the session on the one it already had, not half-switched to
        # a backend whose load failed — and `set store` validating at set
        # time is the feature.
        backend = _make_backend(spec)
        dag = backend.load()
        # A local-first store holds a writer lock and a sync thread; release
        # them when the session moves on (switching back to the same store
        # in one session would otherwise hit its own lock).
        old = getattr(self._dag, "store", None)
        self.spec, self._backend, self._dag = spec, backend, dag
        close = getattr(old, "close", None)
        if close is not None:
            close()

    def save(self):
        self.backend.save(self.dag)

    def describe(self):
        # Describing must not open the store (`odag set` runs with the node
        # down). An unloaded session describes the spec it would open —
        # the same string every backend's describe() echoes back.
        if self._backend is None:
            return self.spec
        return self._backend.describe()

    def import_from(self, incoming):
        """Replace the store's contents with `incoming`, in place.

        Mutating the live DAG (rather than rebinding self.dag) keeps a
        EagerOntoDAG's identity, so its commit() still diffs against what it
        hydrated. Works for either backend via the public API alone: clearing
        to the root then merging reproduces `incoming` exactly (remove
        reconnects children upward, never deletes siblings)."""
        for name in list(self.dag.nodes):
            if name != self.dag.root.name and name in self.dag.nodes:
                self.dag.remove(name)
        self.dag.merge(incoming)
        self.save()


# --------------------------------------------------------------------------- #
# The two output settings that default to `auto` (SURFACE_LAYER.md §7, decided
# 2026-08-01, extended to `limit` 2026-08-02): a terminal gets output meant for
# a person — readable spellings, and only as many lines as are worth reading —
# while anything else gets the complete canonical answer, so `odag get | wc -l`
# counts right and `odag get | odag put` round-trips. Both are OUTPUT-only:
# input elaboration and the query itself never depend on where stdout goes,
# and the tty test is on the actual stream, so `-o FILE` gets canonical bytes.
# --------------------------------------------------------------------------- #

_TTY_LIMIT = 50   # generous enough that ordinary stores never notice it


def _isatty(out):
    try:
        return out.isatty()
    except (AttributeError, ValueError):
        return False


def _want_render(args, out):
    flag = getattr(args, "render_mode", None)
    if flag is not None:
        return flag
    value = _configured("render").strip().lower()
    if value in ("0", "off", "raw", "false", "no"):
        return False
    if value in ("1", "on", "render", "true", "yes"):
        return True
    return _isatty(out)


def _want_limit(args, out):
    """How many result lines to print; 0 means all of them.

    A cap exists so that an interactive query cannot flood the terminal —
    which is what makes the empty query (`odag get`, everything) a safe thing
    to type. It is a DISPLAY cap only: the query itself is always complete,
    the withheld count is always reported, and a pipe is never capped."""
    flag = getattr(args, "limit", None)
    value = _configured("limit", flag)
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("auto", ""):
            return _TTY_LIMIT if _isatty(out) else 0
        if value in ("all", "none", "off"):
            return 0
        try:
            value = int(value)
        except ValueError:
            raise ValueError(
                f"limit must be a number, `all` or `auto`, not {value!r}"
            ) from None
    return max(0, int(value))


def _namer(args, session, out):
    """The name formatter this command's output should use: identity for
    canonical output, the surface renderer for a terminal. Sorting always
    happens on canonical names (the identity); rendering is display-only."""
    if _want_render(args, out):
        return lambda name: _surface.render(name, session.dag)
    return lambda name: name


def _print_names(names, args, session, out):
    """Print result names one per line under the display cap.

    Sorting is on canonical names — the identity — so the prefix a cap keeps
    is the same whether or not output is being rendered. The withheld count
    goes to stderr: it is a message to the person, never part of the answer,
    so it cannot contaminate a pipe even when `-n` was asked for explicitly."""
    fmt = _namer(args, session, out)
    names = sorted(names)
    limit = _want_limit(args, out)
    shown = names[:limit] if limit else names
    for name in shown:
        print(fmt(name), file=out)
    withheld = len(names) - len(shown)
    if withheld:
        print(f"odag: {withheld} more not shown "
              f"(-n 0 for all, or `odag count` for the total)",
              file=sys.stderr)


# --------------------------------------------------------------------------- #
# Command handlers — (args, session, out); silent on success
# --------------------------------------------------------------------------- #

def _print_dag(dag, out, fmt=lambda name: name):
    for node in dag.topological_sort():
        children = sorted(n.name for n in node.neighbors)
        shown = [fmt(c) for c in children]
        if node.name == dag.root.name:
            print(f"{node.name} [root] -> {' '.join(shown)}".rstrip(), file=out)
        else:
            parents = sorted(
                p.name for p in node.parents if dag.nodes.get(p.name) is p
            )
            print(f"{fmt(node.name)} ({' '.join(fmt(p) for p in parents)}) "
                  f"-> {' '.join(shown)}".rstrip(), file=out)


def cmd_put(args, session, out):
    session.dag.put(args.item, args.parents, optimized=args.optimized)
    session.save()


def _disjuncts(categories):
    """Split a command line into DNF — the list of conjunctions `get_any` takes.

    See `_query` for the rules; this is the parse on its own, because the
    commands that *draw* a query need the terms as well as the answer.
    """
    queries, current = [], []
    for category in categories:
        if category == "or":
            queries.append(current)
            current = []
        else:
            current.append(category)
    queries.append(current)
    if len(queries) > 1 and any(not query for query in queries):
        raise ValueError("empty query around 'or'")
    return queries


def _query(categories, dag):
    """Run a command-line query and return the matching items.

    The literal argument `or` separates disjuncts:
        odag get Dog Pet or Cat     ->  (Dog AND Pet) OR Cat
    (`or` is therefore reserved as a category name on the command line;
    a plain AND query is the one-disjunct case.)

    No categories at all is the EMPTY query, which is everything — the
    intersection of no constraints (see `OntoDAG.get`). A *dangling* `or`
    still fails: at that point the empty disjunct is a typo, not a request
    for the universe, and taking it literally would silently turn a narrow
    query into a full dump."""
    queries = _disjuncts(categories)
    if len(queries) == 1:
        return dag.get(queries[0])
    return dag.get_any(queries)


def cmd_get(args, session, out):
    result = _query(args.categories, session.dag)
    _print_names((item.name for item in result), args, session, out)


def cmd_count(args, session, out):
    # How many, and nothing else. Deliberately its own command rather than a
    # flag on `get`: it is the complete answer to "how big is this" — never
    # capped, never rendered — for exactly the cases where printing the answer
    # is what you are trying to avoid.
    print(len(_query(args.categories, session.dag)), file=out)


def cmd_below(args, session, out):
    # A Unix-style boolean, git merge-base --is-ancestor style: prints one
    # parseable word (the interactive prompt has no exit codes) AND exits
    # 0 for true / 1 for false, so `odag below A B && ...` just works.
    # Unknown names are false, not errors (fail-closed, like get).
    result = session.dag.is_below(args.sub, args.sup)
    print("true" if result else "false", file=out)
    return 0 if result else 1


# --------------------------------------------------------------------------- #
# `odag swarm` — the on-ramp, because the wall is the node, not the pip install
# --------------------------------------------------------------------------- #
#
# Putting a DAG on Swarm is five seconds of `pip install` followed by a long
# tail of infrastructure: a node that needs minutes before its chainstate
# answers, a wallet that needs xDAI *and* xBZZ on Gnosis, and a postage batch
# that mainnet refuses to sell below about a day of validity and that stays
# unusable for another minute after you buy it. Each of those used to surface
# as a different error at a different moment, none of them saying which step
# of the sequence you were actually stuck on.
#
# This walks the chain in order and stops at the first thing that is wrong,
# with the command that fixes it. It uses urllib rather than requests on
# purpose: it has to keep working when the swarm extra is the missing piece.

_BEE_INSTALL = (
    "  no node yet? Swarm Desktop is the easiest, it bundles one:\n"
    "    https://docs.ethswarm.org/docs/desktop/introduction/\n"
    "  Bee on its own (servers, always-on nodes):\n"
    "    https://docs.ethswarm.org/docs/bee/installation/quick-start\n"
    # Freedom bundles Ant, which is Bee-compatible but listens on 11633, so
    # naming the port here saves the one confusing failure: a node that is
    # running while odag reports nothing at 1633.
    "  already running Freedom Browser? it has a node on port 11633:\n"
    "    odag set bee_api http://127.0.0.1:11633"
)


def _bee_get(api, path, timeout=4):
    """GET a Bee endpoint using only the standard library."""
    import json
    import urllib.request
    with urllib.request.urlopen(f"{api.rstrip('/')}{path}",
                                timeout=timeout) as response:
        return json.loads(response.read() or b"{}")


def _swarm_checks(api):
    """Yield (ok, label, detail) in dependency order, stopping at the first
    failure — later checks say nothing useful once an earlier one fails."""
    missing = [name for name in ("requests", "swarmfs", "bee")
               if importlib.util.find_spec(name) is None]
    if missing:
        yield (False, "swarm extra installed",
               f"missing {', '.join(missing)}\n"
               '  pip install "ontodag[swarm]"')
        return
    yield (True, "swarm extra installed", "requests, swarmfs, bee")

    # Reachability is asked of /health, not of /: Bee serves the root as
    # `text/plain` ("Ethereum Swarm Bee"), so parsing it as JSON raised
    # JSONDecodeError and reported a perfectly healthy node as "nothing
    # answering" — and since the walk stops at the first failure, that ended
    # the diagnosis and told the user to start a node already running.
    # /health answers JSON, and a 200 from it proves reachability anyway, so
    # the two questions collapse into one honest check.
    try:
        status = _bee_get(api, "/health").get("status", "?")
    except Exception as exc:                              # noqa: BLE001
        yield (False, "node reachable",
               f"nothing answering at {api} ({type(exc).__name__})\n"
               "  start your node, or point odag at another one:\n"
               "    odag set bee_api http://HOST:1633\n" + _BEE_INSTALL)
        return
    yield (True, "node reachable", api)
    yield (status == "ok", "node healthy", f"status={status}")

    # Peers connect long before the chainstate does, and uploads fail until
    # it is up: the single most confusing wait in the whole setup.
    try:
        block = _bee_get(api, "/chainstate").get("block", 0)
    except Exception as exc:                              # noqa: BLE001
        yield (False, "chain synced", f"/chainstate failed ({exc})")
        return
    if not block:
        yield (False, "chain synced",
               "no chainstate yet — a freshly started node can take ~8 "
               "minutes to reach this.\n"
               "  Peers connecting is NOT the signal to wait for; this is.")
        return
    yield (True, "chain synced", f"block {block}")

    try:
        wallet = _bee_get(api, "/wallet")
        bzz = int(wallet.get("bzzBalance", 0) or 0)
        native = int(wallet.get("nativeTokenBalance", 0) or 0)
    except Exception as exc:                              # noqa: BLE001
        yield (False, "wallet funded", f"/wallet failed ({exc})")
        return
    if not (bzz and native):
        yield (False, "wallet funded",
               f"xBZZ={bzz} xDAI={native} — buying postage needs both "
               "(xDAI for gas, xBZZ for the batch).\n"
               f"  the address to fund:  curl -s {api.rstrip('/')}/addresses")
        return
    yield (True, "wallet funded", f"xBZZ={bzz} xDAI={native}")

    try:
        batches = _bee_get(api, "/stamps").get("stamps", [])
    except Exception as exc:                              # noqa: BLE001
        yield (False, "usable postage batch", f"/stamps failed ({exc})")
        return
    usable = [b for b in batches if b.get("usable")]
    if not usable:
        yield (False, "usable postage batch",
               f"{len(batches)} batch(es), none usable.\n"
               "  buy one (depth 17 is a reasonable start; mainnet refuses "
               "less than ~1 day of validity):\n"
               f"    curl -sXPOST {api.rstrip('/')}/stamps/2400000000/17\n"
               "  then wait ~70s — bought and usable are not the same "
               "moment.")
        return
    best = max(usable, key=lambda b: b.get("batchTTL", 0))
    yield (True, "usable postage batch",
           f"{str(best.get('batchID', '?'))[:16]}... "
           f"TTL {best.get('batchTTL', 0) / 86400:.1f} days")

    configured = _configured("bee_batch")
    yield (True, "odag will pay with",
           f"batch {configured}" if configured else
           "batch auto — odag asks the node for a usable one. Pin it with "
           "`odag set bee_batch <id>` to control what gets spent.")
    yield (True, "latest root goes to",
           "a signed Swarm feed, followable by others"
           if _configured("bee_signer") else
           f"a local file in {_home_dir()}. To publish it instead: "
           "odag set bee_signer <private-key>")


def cmd_swarm(args, session, out):
    api = _configured("bee_api")
    print(f"Bee node: {api}", file=out)
    failed = False
    for ok, label, detail in _swarm_checks(api):
        first, _, rest = detail.partition("\n")
        print(f"  [{'ok  ' if ok else 'FAIL'}] {label:22} {first}", file=out)
        if rest:
            print(rest, file=out)
        failed = failed or not ok
    if failed:
        print("\nFix the first FAIL above, then run `odag swarm` again.\n"
              "Not ready to run a node? `odag set store rs:~/work/mydag` "
              "gives you the same\ncanonical roots, snapshots and "
              "certificates on local disk, with no node at all.", file=out)
        return 1
    print("\nReady:  odag set store swarm:mydag", file=out)
    return 0


def cmd_index(args, session, out):
    # Publish cone summaries next to the store (CONE_SUMMARIES_PLAN step E):
    # a derived index in a SEPARATE record store, so the data root is
    # untouched. Prints the manifest pair — hand both roots to lazy readers.
    backend = session.backend
    if not isinstance(backend, (SwarmBackend, LocalRecordBackend)):
        raise ValueError(
            "index needs a record-store backend (rs:PATH or swarm:NAME); "
            "the native text store is loaded whole and never benefits "
            "from one")
    from ontodag.cones import build_index

    data_root = session.dag.store.root
    if not data_root:
        raise ValueError("nothing committed yet — put something first")
    index_store = backend.index_record_store()
    try:
        index_root = build_index(session.dag, index_store,
                                 data_root, threshold=args.threshold)
    finally:
        # transient window: a local-first index store holds a writer lock
        close = getattr(index_store, "close", None)
        if close is not None:
            close()
    print(f"data  {data_root}", file=out)
    print(f"index {index_root}", file=out)


def cmd_remove(args, session, out):
    """Remove items — by contraction, or with `--cone` by deletion.

    Two operations, deliberately under one command with the destructive one
    behind a word you have to type:

    * Default: **contract**. Each named category goes and its children reattach
      to its parents, so nothing below it is lost. Removing several is
      order-independent (measured over random DAGs and every removal order), so
      it is a function of the set — which is why several names are allowed at
      all, and why the order they are typed in cannot matter.
    * `--cone`: **delete** the category and whatever only existed underneath it.
      A cone member that also hangs elsewhere survives; one whose every parent
      was in the cone goes with it (`OntoDAG.cone_removal_plan`). This is what
      "remove the whole subgraph" has to mean in a multi-parent DAG — looping
      the default over a cone would destroy the multi-parent members too.

    Names are all resolved before anything moves, so an unknown name leaves the
    store untouched rather than half-removed. `--dry-run` prints what would go
    and changes nothing; the counts afterwards go to stderr, since they are a
    message to the person and not the answer to anything.
    """
    dag = session.dag
    if not args.cone:
        names = dag._resolve_for_removal(args.items)     # all-or-nothing
        if args.dry_run:
            _print_names(names, args, session, out)
            return 0
        for name in names:
            dag.remove(name)
        session.save()
        return 0

    cone, deleted = dag.cone_removal_plan(args.items)
    if args.dry_run:
        _print_names(deleted, args, session, out)
        _cone_note(len(deleted), cone - deleted, args, session,
                   "would delete", out)
        return 0

    dag.remove_cone(args.items)
    session.save()
    _cone_note(len(deleted), cone - deleted, args, session, "deleted")
    return 0


def cmd_move(args, session, out):
    """Reclassify items: file them under new categories, retract the old ones.

    `put` only adds a parent and `remove` deletes the item, so this is the
    missing third operation — and the one a lifecycle needs. Doing it by hand as
    remove-then-put loses the subtree: the children reattach to the old parent
    and stay there while the item moves on alone.

    Three shapes, from the two optional halves:

        move X --to archive                 X is under archive, and nothing else
        move X --from active --to archive   surgical: that one classification
        move X --from active                unfile it (top-level if that was all)

    The **contested set** is the report worth reading: moving `A` moves
    everything below it, but a child that also hangs under a still-active `B`
    ends up archived *and* active. That is true — a shared document really is in
    both situations — and it is not something the DAG can decide, because
    subsumption inherits and exclusive status cannot. So it is named, counted,
    and left to you. `--dry-run` shows it before you commit, computed by
    performing the move on a copy, so the preview cannot drift from the act.
    """
    if not args.to and not args.from_:
        raise ValueError("nothing to do: give --to, --from, or both")

    dag = session.dag
    news = [dag._canonical_name(name) for name in args.to]
    if args.from_:
        olds = sorted({dag._canonical_name(name) for name in args.from_})
    else:
        # No --from: the old categories are whatever they are under now, which
        # has to be read before the move, not after.
        olds = sorted({name
                       for item in args.items
                       for name in dag._live_parent_names(
                           dag._canonical_name(item))
                       if name != dag.root.name})
    before = {old: {item.name for item in dag.get([old])}
              for old in olds if old in dag.nodes}

    # A dry run performs the real move on a copy, so the preview cannot drift
    # from the act — including its refusals, which are raised either way.
    target = dag.deepcopy() if args.dry_run else dag
    target.reclassify(args.items, to=args.to, from_=args.from_ or None)

    if args.dry_run:
        _print_names(_reclassified(dag, target), args, session, out)
        _move_note(target, before, news, args, session, "would move", out)
        return 0

    session.save()
    _move_note(target, before, news, args, session, "moved", None)
    return 0


def _reclassified(before, after):
    """Items whose classification differs between two versions of a store.

    The answer to "what does this actually change?", which is never only the
    items named: everything below them travels with them."""
    def ancestors(dag, name):
        return {node.name for node in dag.get_ancestors(name, computed=False)}

    return {name for name in set(before.nodes) & set(after.nodes)
            if ancestors(before, name) != ancestors(after, name)}


def _move_note(dag, before, news, args, session, verb, out):
    """What left each old category, and what is now in two states at once.

    The second half is the point (see `cmd_move`): a move can leave a shared
    item under both the old and the new category, which is a true statement the
    DAG cannot resolve for you, so it gets named rather than hidden."""
    flush = getattr(out, "flush", None)
    if flush is not None:
        flush()                      # or the note prints above its own listing
    fmt = _namer(args, session, sys.stderr)

    segments = []
    for old, members in sorted(before.items()):
        remaining = ({item.name for item in dag.get([old])}
                     if old in dag.nodes else set())
        departed = len(members - remaining)
        segment = (f"{departed} item{'' if departed == 1 else 's'} "
                   f"left {fmt(old)}")
        # Only pairs that are genuinely in tension. Moving something to a
        # category *below* the one it left keeps it under both by entailment —
        # that is refinement, not a contested state, and reporting it would cry
        # wolf on the most ordinary move there is.
        contested = sorted({item.name for new in news
                            if new != old and new in dag.nodes
                            and not dag.is_below(new, old)
                            and not dag.is_below(old, new)
                            for item in dag.get([old, new])})
        if contested:
            shown = " ".join(fmt(name) for name in contested[:5])
            more = f" +{len(contested) - 5} more" if len(contested) > 5 else ""
            others = " and ".join(fmt(new) for new in sorted(set(news))
                                  if new != old)
            segment += (f", {len(contested)} still in both {fmt(old)} and "
                        f"{others} ({shown}{more})")
        segments.append(segment)
    if not segments:
        segments = ["nothing was filed anywhere else"]
    print(f"odag: {verb}: {'; '.join(segments)}", file=sys.stderr)


def _cone_note(deleted, survivors, args, session, verb, out=None):
    """What a cone removal did, and what it deliberately spared."""
    # Flushed first, or a block-buffered stdout (any pipe) prints the note
    # above the list it is about — same reason `diff`'s summary flushes.
    flush = getattr(out, "flush", None)
    if flush is not None:
        flush()
    fmt = _namer(args, session, sys.stderr)
    kept = ""
    if survivors:
        shown = sorted(survivors)[:5]
        more = f", +{len(survivors) - len(shown)} more" if len(survivors) > len(shown) else ""
        kept = (f"; kept {len(survivors)} that hang elsewhere too "
                f"({' '.join(fmt(name) for name in shown)}{more})")
    print(f"odag: {verb} {deleted} item{'' if deleted == 1 else 's'}{kept}",
          file=sys.stderr)


def cmd_show(args, session, out):
    _print_dag(session.dag, out, fmt=_namer(args, session, out))


def cmd_list(args, session, out):
    # `list` is the empty query under a discoverable name — one code path, so
    # `odag list`, `odag get` and `odag get '*'` cannot drift apart.
    _print_names((item.name for item in session.dag.get([])),
                 args, session, out)


def cmd_prelude(args, session, out):
    # The declaration-ceremony answer (SURFACE_LAYER.md §9.2): adopt the
    # standard dimension declarations by an explicit, idempotent MERGE —
    # never as a silent default of a fresh store, so the root change is
    # a visible, versioned act of adoption.
    from ontodag.prelude import DECLARATIONS, PRELUDE_VERSION, prelude_dag
    if args.show:
        print(f"# ontodag prelude v{PRELUDE_VERSION}", file=out)
        for name, parents in DECLARATIONS:
            print(" ".join([name, *parents]), file=out)
        return
    session.dag.merge(prelude_dag())
    session.save()


def cmd_pack(args, session, out):
    # Unit packs (UNITS.md §7): graph-declared vocabulary adopted by an
    # explicit, idempotent merge — the prelude pattern, for units. The
    # vocabulary then travels inside the store itself.
    from ontodag.packs import PACKS, pack_dag
    if not args.name:
        for name in sorted(PACKS):
            version, declarations = PACKS[name]
            print(f"{name} v{version} ({len(declarations)} declarations)",
                  file=out)
        return
    if args.show:
        version, declarations = PACKS.get(args.name, (None, None))
        if declarations is None:
            raise ValueError(f"unknown pack {args.name!r} "
                             f"(available: {', '.join(sorted(PACKS))})")
        print(f"# ontodag pack {args.name} v{version}", file=out)
        for declaration in declarations:
            print(declaration, file=out)
        return
    session.dag.merge(pack_dag(args.name))
    session.save()


def cmd_canon(args, session, out):
    # The inspectable mapping (SURFACE_LAYER.md §7): what does this surface
    # term elaborate to? Output is always canonical — that is the command's
    # whole point — so it ignores the render mode. A malformed parameter of
    # a declared head raises the core's own teaching error (exit 1). With no
    # term it prints the surface and registry versions (§9.5: informational,
    # never stored).
    if not args.term:
        print(f"surface {_surface.SURFACE_VERSION}", file=out)
        print(f"registry {REGISTRY_VERSION}", file=out)
        return
    print(_surface.elaborate(args.term, session.dag), file=out)


def cmd_merge(args, session, out):
    session.dag.merge(_load(args.file))
    session.save()


def cmd_import(args, session, out):
    session.import_from(_load(args.file))


def cmd_export(args, session, out):
    _save(session.dag, args.file)


def _excerpt_names(dag, categories, context):
    """The name set an excerpt covers: the answer, optionally ancestor-closed.

    `--context` adds the *asserted* ancestors of every answer — the categories
    the answers hang from, up to the root. Asserted only, deliberately: the
    computed order (a value below a coarser value of its dimension) is derived
    from names plus declarations, so the reader recomputes it, and copying
    those coarser values in would drag unrelated star members along with it.
    The declarations themselves DO travel, because a head node like `weight`
    is a real asserted parent of its values and therefore an ancestor.
    """
    answer = _query(categories, dag)
    names = {item.name for item in answer}
    if context:
        for item in answer:
            names |= {a.name for a in dag.get_ancestors(item, computed=False)}
    names.discard(dag.root.name)
    return names


def cmd_excerpt(args, session, out):
    """Write a query's answer, with its own structure, to a file.

    The materialized half of the pair `dag.py` already had: `intersection_dag`
    is the live *view*, `copy_subdag` is the *excerpt* — this is the excerpt
    under a name. `export` writes the whole store; this writes one principal
    down-set of it (order theory's ideal, the descendant cone).

    Two deliberate properties of the default:

    * Query terms are NOT added as nodes, even though the web surface's
      *picture* does exactly that. A picture is drawn and discarded, so
      inventing a node to show a constraint costs nothing; an excerpt exists
      to be `odag import`ed back, and inventing that node would file the
      constraint as knowledge.
    * The answer's own topmost nodes are hung under the excerpt's root, so
      the file is a well-formed OntoDAG (`*` is the ancestor of every
      top-level item) and `list`/`get` in the importing store see them. The
      real edges *within* the answer are copied, so the shape survives:
      cones are downward-closed under intersection, which is why the answer
      carries its structure at all.

    `--context` is for sending it somewhere. Measured, not assumed: merging a
    plain cut into a store that has your upper categories but not these items
    files them at TOP LEVEL — `get Japan` comes back empty, because the edges
    that made them answers pointed at the query terms, which the default drops.
    With `--context` the answers arrive classified exactly as here, nothing is
    invented (every node and edge is real, root edges included), siblings do
    not leak, and the file becomes *diffable* against this store instead of
    reading as a wholesale deletion of everything outside it. The cost is that
    it discloses the shape of the categories above the answer.
    """
    names = _excerpt_names(session.dag, args.categories, args.context)
    excerpt = session.dag.induced_subdag(names)
    for name in sorted(excerpt.nodes):
        node = excerpt.nodes[name]
        if node is not excerpt.root and not node.parents:
            excerpt.add_edge(excerpt.root, node)
    _save(excerpt, args.file)


def _parents_in(dag, name):
    node = dag.nodes[name]
    return sorted(p.name for p in node.parents
                  if dag.nodes.get(p.name) is p and p.name != dag.root.name)


def _asserted_edges(dag, scope):
    """Asserted parent→child pairs with BOTH ends in scope, as (child, parent)."""
    return {(name, parent)
            for name in scope if name in dag.nodes
            for parent in _parents_in(dag, name) if parent in scope}


def _entailed_claims(dag, scope):
    """Every `sub ⊑ sup` the store entails within scope — the honest unit.

    Combined order (asserted edges *and* the computed order between parametric
    values), because that is what the store answers `below` with, and a
    difference in what two stores entail is a real difference even when no edge
    moved. Restricted to scope on both ends so a scoped comparison stays
    bounded: the unscoped case walks every cone, which is a report's cost, not
    a query's."""
    claims = set()
    for name in scope:
        node = dag.nodes.get(name)
        if node is None:
            continue
        for descendant in dag.get_descendants(node):
            if descendant.name != name and descendant.name in scope:
                claims.add((descendant.name, name))
    return claims


def cmd_diff(args, session, out):
    """What OTHER has that this store doesn't, and the other way round.

    `+` is OTHER, `-` is here — `diff mine theirs` order, so the lines read as
    what would arrive if you merged it (bar the removals, which `merge` cannot
    apply: it is grow-only by design).

    Two decisions, both measured rather than assumed (see CHANGELOG):

    * **Claims decide, edges display.** Comparing reduced edge sets accuses
      people of deletions they did not make: adding one edge can prune two
      others while entailing strictly more — one `put` measured as
      `edges +1 -2` with *zero* claims lost. So an edge that vanished is
      reported only when the claim it carried vanished too (`is_below` on the
      other side settles it). Conversely, claims alone cascade with depth (a
      leaf added twelve levels down is +14 claims), so the listing stays at
      edge grain and the cascade is a count on the summary line.
    * **Parents, not paths, locate a change.** In a multi-parent DAG there is
      no single path to root, so the honest locator is where the item hangs.
      `odag show` and `odag visualize CAT...` give the surroundings.

    Scope: with categories, both sides are cut to the same set an
    `excerpt --context` would take (the answer plus its asserted ancestors),
    which is what makes comparing a cut against the store it came from
    meaningful — unscoped, everything outside the cut reads as a deletion.

    `--additions PATH` writes OTHER's additions as an ordinary store file that
    `merge` applies. It is called `--additions` and not `--patch` because
    that is exactly what it is *and what it is not*: merging the fragment was
    measured to reach the byte-identical root to merging OTHER whole, so the
    additive half of a patch is not a new mechanism — but removals cannot be
    in it. Not "not yet": a removal is lossy (`remove X` contracts children
    onto X's parents, and putting X back does not restore them) and does not
    commute with a concurrent addition (`remove` then `add` fails outright,
    `add` then `remove` silently gives a different graph), so a file whose
    effect depends on when you apply it cannot be a fold. Removals belong to
    a base-pinned three-way apply, and travel as attributed retractions
    (PROVENANCE.md) rather than as graph operations. When there are any, this
    says so rather than shipping a file that quietly drops them.

    NOTE this is two-way. It cannot distinguish "they deleted it" from "I added
    it after sending" — that needs the base you sent (three-way), which `rs:`
    and `swarm:` stores record for free as the root you were at.
    """
    # A missing native store reads as empty everywhere else (a fresh store need
    # not exist yet), but for a comparison that convention is a trap: a typo in
    # the path would report the entire store as deleted, which is exactly the
    # answer someone reviewing a merge must not be handed by accident.
    if not os.path.exists(args.other):
        raise ValueError(
            f"{args.other}: no such file — refusing to compare against an "
            f"empty store, which would report everything here as removed")

    mine, theirs = session.dag, _load(args.other)

    if args.categories:
        scope = (_excerpt_names(mine, args.categories, context=True)
                 | _excerpt_names(theirs, args.categories, context=True))
    else:
        scope = ((set(mine.nodes) | set(theirs.nodes))
                 - {mine.root.name, theirs.root.name})

    only_mine = sorted(n for n in scope if n in mine.nodes and n not in theirs.nodes)
    only_theirs = sorted(n for n in scope if n in theirs.nodes and n not in mine.nodes)
    common = scope - set(only_mine) - set(only_theirs)

    # Edge changes between items BOTH sides have; an item that only one side
    # has carries its parents on its own line, so listing its edges as well
    # would say the same thing twice.
    added = sorted(edge for edge in _asserted_edges(theirs, common)
                   - _asserted_edges(mine, common)
                   if not mine.is_below(*edge))
    removed = sorted(edge for edge in _asserted_edges(mine, common)
                     - _asserted_edges(theirs, common)
                     if not theirs.is_below(*edge))

    fmt = _namer(args, session, out)

    def item_line(sign, dag, name):
        parents = " ".join(fmt(p) for p in _parents_in(dag, name))
        return f"{sign} item {fmt(name)}" + (f" ({parents})" if parents else "")

    lines = [item_line("-", mine, name) for name in only_mine]
    lines += [item_line("+", theirs, name) for name in only_theirs]
    lines += [f"- below {fmt(sub)} {fmt(sup)}" for sub, sup in removed]
    lines += [f"+ below {fmt(sub)} {fmt(sup)}" for sub, sup in added]
    for line in lines:
        print(line, file=out)

    if args.additions:
        # Their new items with the parents they hang from, plus both ends of
        # each new claim: the minimum that merges to the same place. The
        # parents need no ancestors of their own — an item that arrives
        # parentless here already exists properly in the receiving store, and
        # the redundant root edge is dropped by reduction on merge (the same
        # property that makes a plain excerpt absorb).
        names = set(only_theirs)
        for name in only_theirs:
            names |= set(_parents_in(theirs, name))
        for sub, sup in added:
            names |= {sub, sup}
        # Written even when empty, so a script can merge it unconditionally.
        _save(theirs.induced_subdag(names), args.additions)

    if not lines:
        return 0                        # identical in scope: silent, like diff(1)

    # The cascade, and the scope it was measured over — a message to the
    # person, so stderr, exactly like the display cap's withheld count.
    # Flushed first: a block-buffered stdout (any pipe) would otherwise put
    # the summary above the changes it summarizes under `2>&1 | less`.
    flush = getattr(out, "flush", None)
    if flush is not None:
        flush()
    ours = _entailed_claims(mine, scope)
    yours = _entailed_claims(theirs, scope)
    print(f"odag: +{len(only_theirs)}/-{len(only_mine)} items, "
          f"+{len(added)}/-{len(removed)} claims listed; "
          f"+{len(yours - ours)}/-{len(ours - yours)} entailed claims "
          f"over {len(scope)} names", file=sys.stderr)

    # Said out loud, always: a fragment that silently dropped the removals
    # would look like the whole change to whoever merges it next.
    if args.additions and (only_mine or removed):
        dropped = len(only_mine) + len(removed)
        print(f"odag: {dropped} removal{'' if dropped == 1 else 's'} "
              f"{'is' if dropped == 1 else 'are'} NOT in {args.additions} — "
              f"merge only ever adds. The `- ` lines above are the whole of "
              f"what it leaves out.", file=sys.stderr)
    return 1                            # differences found (grep-style, like `below`)


def _image_base(spec):
    """Default output name for `visualize`: named after the store.

    Every backend gets a name from this, because there is no `--out`-less
    fallback that works otherwise. `visualize` read `session.path` until
    `rs:` stores arrived and Session stopped having one, which made bare
    `odag visualize` raise AttributeError from 0.12.0 to 0.15.0 — nothing
    caught it because no test ever omitted `--out`.
    """
    if _is_swarm(spec):
        return spec[len("swarm:"):]                 # cwd/NAME.png
    if _is_record_store(spec):
        return os.path.normpath(spec[len("rs:"):])  # the store dir, +.png
    return os.path.splitext(spec)[0]                # beside the .od file


def cmd_visualize(args, session, out):
    """Draw the store, or — given categories — draw just that query.

    The drawn twin of `excerpt`, and deliberately not the same view. An
    excerpt is a file that gets imported back, so it must not contain the
    constraint you searched with; a picture is drawn and discarded, so the
    query terms ARE drawn (as nodes, even when the store has no such node —
    a virtual term like `weight(..5kg)` never does), because a picture of an
    answer that does not show what was asked is half a picture. Shaping lives
    in `ontodag.viz.query_picture`, shared with the web surface so the two
    cannot drift.

    With no categories the query is unconstrained, and everything already has
    a picture: draw the store itself rather than the empty query's view,
    whose root node would be an invented `*` above a copy of `*`.
    """
    from ontodag.viz import OntoDAGVisualizer, query_picture
    base = args.out or _image_base(session.describe())
    dag = session.dag
    queries = _disjuncts(args.categories)
    if any(queries):
        dag = query_picture(dag, queries)
    OntoDAGVisualizer(format=args.format).visualize(dag, filename=base)


def _effective_setting(session, key):
    """The value currently in effect, by the settings table's one rule.

    `store` is the exception worth having: what is in effect is the store this
    session actually opened, which is not the configured spec if a `set store`
    was saved but could not be switched to."""
    if key == "store":
        return session.describe()
    return _configured(key)


_GENERATE = "generate"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _looks_like_a_signer(value):
    """32 bytes as hex, `0x` prefix optional — what `PrivateKey.from_hex` takes."""
    raw = value[2:] if value[:2].lower() == "0x" else value
    return len(raw) == 64 and all(c in _HEX_DIGITS for c in raw)


def _signer_to_store(value, force):
    """The value to write for `bee_signer`: generated on request, checked always.

    `odag set bee_signer generate` exists because the alternative is asking
    people to type a shell incantation to produce 32 random bytes, which is
    both hostile and easy to get subtly wrong — a stray character gives a
    65-character string that only fails later, at the first command that opens
    the store. `generate` cannot collide with a real value: a signer is always
    64 hex characters.

    Generating over an existing key is refused by default. The feed's address
    is derived from the key, so replacing it strands whoever follows the old
    feed at the last root published there, and the old key is unrecoverable
    unless it was backed up. That is not something to do as a side effect of a
    command that looks like it sets a preference.
    """
    if value != _GENERATE:
        if not _looks_like_a_signer(value):
            raise ValueError(
                f"bee_signer must be 32 bytes as hex — 64 characters, "
                f"optionally 0x-prefixed; got {len(value)}.\n"
                f"  to make one: odag set bee_signer {_GENERATE}")
        return value

    if _read_config().get("bee_signer") and not force:
        raise ValueError(
            "a signing key is already configured, and replacing it would "
            "strand the feed the current one publishes: anyone following it "
            "stays at the last root you pushed, and the old key is gone "
            "unless you backed it up.\n"
            f"  if you mean it: odag set bee_signer {_GENERATE} --force")

    import secrets                      # stdlib, but only this path needs it
    key = secrets.token_hex(32)
    # On stderr, not stdout: `set` is silent on success by convention. But a
    # secret the user will never be shown again is exactly the case where
    # silence is unhelpful — they have to know it exists to back it up.
    print(f"odag: generated a signing key, stored in {_config_path()} "
          f"(<hidden, ends {key[-4:]}>).\n"
          f"  back it up — the feed address comes from this key, so losing it "
          f"means that feed can never be updated again.", file=sys.stderr)
    if os.environ.get("BEE_SIGNER"):
        print("  note: BEE_SIGNER is set in this environment and outranks the "
              "config file, so the generated key will not take effect until "
              "you unset it.", file=sys.stderr)
    return key


def _shown_setting(session, key):
    """A setting's effective value, in a form safe to print.

    A secret is reported as set, with its last four characters so two keys can
    be told apart, and never in full: `odag set` is what you run to see your
    configuration, so whatever it prints ends up in scrollback and screen
    shares. The value itself stays in the config file, which is the place to
    read it from — deliberately not through a display command."""
    value = _effective_setting(session, key)
    if _SETTINGS[key].secret and value:
        return f"<hidden, ends {value[-4:]}>"
    return value


def cmd_set(args, session, out):
    # No key: show every setting. Key but no value: show that one. Both:
    # change it — writing to the config file, which is the durable layer;
    # a flag or an environment variable still outranks it for that run.
    # Displaying on a missing value never errors.
    if not args.key:
        for key in sorted(_SETTINGS):
            print(f"{key} = {_shown_setting(session, key)}", file=out)
        return
    if args.key not in _SETTINGS:
        raise ValueError(f"unknown setting: {args.key} "
                         f"(known: {', '.join(sorted(_SETTINGS))})")
    if args.value is None:
        print(f"{args.key} = {_shown_setting(session, args.key)}", file=out)
        return
    if args.key == "store":
        spec = _normalize_spec(args.value)
        cfg = _read_config()
        cfg["store"] = spec
        _write_config(cfg)
        try:
            session.switch(spec)
        except (ValueError, OSError) as exc:
            # The setting is saved regardless: configuring a store you can't
            # reach yet is legitimate (start the node afterwards). Say so, so
            # the failure doesn't read as "nothing happened".
            raise ValueError(
                f"{exc}\n  the `store` setting was still saved as {spec}; "
                f"this session keeps using {session.spec}"
            ) from exc
    else:
        # Validate now, not at the next command that reads it: a setting that
        # only fails later is a setting you debug in the wrong place.
        if args.key == "limit":
            _want_limit(argparse.Namespace(limit=args.value), out)
        value = args.value
        if args.key == "bee_signer":
            value = _signer_to_store(value, getattr(args, "force", False))
        cfg = _read_config()
        cfg[args.key] = value
        _write_config(cfg)


HELP_TEXT = """\
Usage: odag [-f STORE] <command> [args]

Commands:
  put SUB [PARENT...]   add SUB under the PARENT categories (or the root)
  get [CAT...]          print items below all of the CATs, one per line
                        (the literal word `or` separates alternatives:
                        `get Dog Pet or Cat` = (Dog AND Pet) OR Cat).
                        With no CAT at all the query is unconstrained, so
                        it prints everything — the same as `list`
  count [CAT...]        how many items that same query matches: one number,
                        complete, never capped
  below SUB SUP       does SUB fit within SUP? prints true/false and
                        exits 0/1 (grep-style), so `odag below A B && ...`
                        works; `?` is a synonym at the interactive prompt.
                        Works on typed values from the names alone:
                        below 'weight(3kg)' 'weight(..5kg)' -> true
  move ITEM... --to CAT [--from CAT]
                        reclassify: file the items under --to and retract
                        their old categories. --from picks which one to
                        retract (default: all of them, so --to alone means
                        `under this and nothing else`); --to alone omitted
                        unfiles them. Everything below an item travels with
                        it, and anything left under BOTH the old and new
                        category is reported. --dry-run to look first
  remove ITEM...        remove items: each one goes and its children
                        reattach to its parents, so nothing below is lost
                        (the order you name them in cannot matter).
                        --cone instead DELETES each item and whatever only
                        existed under it — a member of the cone that also
                        hangs elsewhere survives. --dry-run prints what
                        would go and changes nothing
  show                  print the DAG structure
  list                  print every item name (the empty query, named)
  merge FILE            merge FILE into the store
  import FILE           replace the store with the contents of FILE
  export FILE           write the store to FILE
  excerpt FILE [CAT...] write just that query's answer to FILE, with the
                        edges among the answers kept — an importable cut of
                        the store (`export` is the whole thing).
                        --context also writes the categories the answers
                        hang from, which is what makes the file usable
                        somewhere else: merged into another store the
                        answers keep their classification, and it can be
                        diffed against the store it came from
  diff FILE [CAT...]    compare this store with FILE: `+ ` is FILE's, `- `
                        is ours; exits 0 if identical, 1 if not. A CAT list
                        compares only that part of both stores.
                        --additions PATH also writes FILE's additions as a
                        store file `merge` can apply — removals cannot be
                        in one, and it says so when there are any
  visualize [CAT...]    render an image (--out B, --format png|svg|pdf).
                        With CATs, draws just that query's answer, with
                        the query terms shown above it — a picture is
                        discarded, so unlike `excerpt` it can show what
                        was asked
  swarm                 check the Swarm setup step by step (node, chain,
                        wallet, postage batch) and print what to fix next
  index [--threshold N] publish cone summaries for a swarm: store into the
                        sibling NAME-index store (a derived index: the data
                        root is untouched); prints both roots for readers
  canon [TERM]          print TERM's canonical form — what would actually be
                        stored (`canon 'time(2026)'` shows the timestamp
                        range); with no TERM, the surface/registry versions
  prelude [--show]      adopt the standard dimension declarations (weight,
                        time, geo, size, ...) in one idempotent merge;
                        --show prints them instead
  pack [NAME] [--show]  list unit packs, or adopt one (crypto-majors,
                        stablecoins, fiat-iso4217) — vocabulary as graph
                        data, no new release needed; travels with the store
  set [KEY [VALUE]]     show settings, or set one durably (store, bee_api,
                        bee_batch, bee_signer, render, limit).
                        `set bee_signer generate` makes a signing key for you
                        and stores it without displaying it
  help                  show this help

With no command odag reads commands from a pipe, or opens an interactive
prompt on a terminal. Files ending in .owl/.omn use OWL/Manchester syntax;
any other path is the native line format.

Typed values: run `odag prelude` once (or declare by hand: put dimension;
put linear-dimension dimension; put weight linear-dimension), then use
parametric terms anywhere a category goes — put parcel 'weight(3kg)',
get 'weight(..5kg)' (quote the parentheses in a shell). Values are
exact rationals of the SI anchor unit (500g is stored as 1/2kg; any
exact unit works, psi to shaku — see docs/UNITS.md); ranges
are lo..hi with either end open. For dates use calendar-dimension
instead of linear-dimension: then 'time(2026)' is the year,
'time(2026-08)' the month, 'time(2026-08-15)' the day, and each
contains the finer ones. For whole numbers of things use the prelude's
count head: put bouquet 'count(24)', get 'count(20..)' — counts start
at 1 (count(0) would claim an absence, which an open-world store
cannot assert) and fractions refuse. See docs/DIMENSIONS.md.

Output for people vs output for programs: on a terminal, names print in
friendly spellings — weight(3kg), time(2026) — and long answers stop at 50
lines with a note on stderr saying how many were withheld. Pipes, files and
-o get the complete answer in exact canonical bytes, so `odag get ... | odag`
round-trips and `odag get ... | wc -l` counts right. Override with
--render / --raw and -n N (-n 0 for all). `canon TERM` shows the exact
stored form of any spelling. See docs/plans/SURFACE_LAYER.md.

Settings: store, bee_api, bee_batch, bee_signer, render, limit. Each can be
given four ways, and the first that is present wins:

  flag  >  environment  >  config file (`set`)  >  default

so a flag is for one command, an environment variable for one shell, and
`odag set KEY VALUE` is the durable one (it writes ~/.ontodag/config).
`odag set` with no arguments prints what is currently in effect.

Beyond a plain file, a store can be:

  rs:PATH        a content-addressed record store on local disk. Gives you
                 canonical roots (equal knowledge, equal root), snapshots,
                 verifiable is_below certificates and multi-writer sync —
                 all of it with no node and no network. The step to take
                 before Swarm, and the way to see what Swarm is for.
  swarm:NAME     the same store, on Ethereum Swarm. Run `odag swarm` first:
                 it checks the node, chain, wallet and postage batch in
                 order and tells you which one to fix.

A store may also be `swarm:NAME`, persisted on Ethereum Swarm (content on a
Bee node, latest root in ~/.ontodag/NAME.root). `set store swarm:NAME` makes
it the default, so every later command uses Swarm. Needs the swarm extra
(`pip install -e ".[swarm]"`). Configure the node with $BEE_API / $BEE_BATCH
(and $BEE_SIGNER to publish the latest root to a followable Swarm feed
instead of keeping it in a local file)
or `bee_api` / `bee_batch` in ~/.ontodag/config.

The store can also be browsed as a filesystem (paths as category queries,
FUSE-mountable) with `odag-fs`, which shares these settings — see
https://github.com/petfold/ontodag-fs.

Options (before the command; they apply to every command in a batch):
  -f, --store PATH      use PATH (or swarm:NAME) as the store for this run
  -n, --limit N         show at most N results (0 for all)
  --render, --raw       force friendly or canonical names
  --bee-api URL         Bee node endpoint, for swarm: stores
  --bee-batch ID        postage batch to pay for Swarm writes
  --bee-signer KEY      publish the latest root to a signed Swarm feed

Per command:
  -o, --output FILE     write output to FILE instead of stdout (get/show/list)
  -n, --limit N         as above, for this command only (get/list)
  --render, --raw       as above, for this command only

Documentation: https://github.com/petfold/ontodag/tree/main/docs
(USER_GUIDE.md is the tutorial, REFERENCE.md the compact lookup.)
"""


def cmd_help(args, session, out):
    print(HELP_TEXT, file=out, end="")


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def _add_surface_flags(p):
    """--render/--raw on every command whose stdout carries names. The pair
    overrides $ONTODAG_SURFACE and the tty default (§7 precedence)."""
    group = p.add_mutually_exclusive_group()
    group.add_argument("--render", dest="render_mode", action="store_const",
                       const=True, help="friendly names even when piped")
    group.add_argument("--raw", dest="render_mode", action="store_const",
                       const=False, help="canonical names even on a terminal")
    p.set_defaults(render_mode=None)


def _add_limit_flag(p):
    """-n on every command that prints a list of names. Overrides
    $ONTODAG_LIMIT, the `limit` setting and the tty default; 0 means all."""
    p.add_argument("-n", "--limit", metavar="N",
                   help="show at most N results (0 for all)")


def build_parser():
    parser = argparse.ArgumentParser(prog="odag", add_help=False,
                                     description="Manipulate an OntoDAG store.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    p = sub.add_parser("put", add_help=True, help="add an item")
    p.add_argument("item")
    p.add_argument("parents", nargs="*")
    p.add_argument("--optimized", action="store_true",
                   help="infer most-specific parents")
    p.set_defaults(func=cmd_put)

    p = sub.add_parser("get", add_help=True, help="query common subcategories")
    p.add_argument("categories", nargs="*")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    _add_limit_flag(p)
    p.set_defaults(func=cmd_get, stream_output=True)

    p = sub.add_parser("count", add_help=True,
                       help="how many items a query matches")
    p.add_argument("categories", nargs="*")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_count, stream_output=True)

    p = sub.add_parser("below", add_help=True,
                       help="test whether SUB fits within SUP (exit 0/1)")
    p.add_argument("sub")
    p.add_argument("sup")
    p.set_defaults(func=cmd_below, stream_output=True)

    p = sub.add_parser("swarm", add_help=True,
                       help="check whether this machine can talk to Swarm, "
                            "and say what to fix")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_swarm, stream_output=True)

    p = sub.add_parser("index", add_help=True,
                       help="publish cone summaries for a swarm store")
    p.add_argument("--threshold", type=int, default=64,
                   help="summarize categories with at least this many "
                        "descendants (default 64)")
    p.set_defaults(func=cmd_index, stream_output=True)

    p = sub.add_parser("move", add_help=True,
                       help="reclassify items: file under new categories, "
                            "retract the old ones")
    p.add_argument("items", nargs="+")
    p.add_argument("--to", nargs="+", default=[], metavar="CAT",
                   help="the categories the items should be under now")
    p.add_argument("--from", dest="from_", nargs="+", default=[], metavar="CAT",
                   help="which classifications to retract (default: all of "
                        "them, so `--to` alone means `under this and nothing "
                        "else`)")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would be reclassified and change nothing")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    _add_limit_flag(p)
    p.set_defaults(func=cmd_move, stream_output=True)

    p = sub.add_parser("remove", add_help=True,
                       help="remove items (contract), or --cone (delete)")
    p.add_argument("items", nargs="+")
    p.add_argument("--cone", action="store_true",
                   help="delete each item and whatever only existed under it, "
                        "instead of reattaching its children to its parents")
    p.add_argument("--dry-run", action="store_true",
                   help="print what would go and change nothing")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    _add_limit_flag(p)
    p.set_defaults(func=cmd_remove, stream_output=True)

    p = sub.add_parser("show", add_help=True, help="print the DAG structure")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    p.set_defaults(func=cmd_show, stream_output=True)

    p = sub.add_parser("list", add_help=True, help="print all item names")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    _add_limit_flag(p)
    p.set_defaults(func=cmd_list, stream_output=True)

    p = sub.add_parser("pack", add_help=True,
                       help="list unit packs, or adopt one by merge "
                            "(--show to inspect)")
    p.add_argument("name", nargs="?")
    p.add_argument("--show", action="store_true",
                   help="print the pack instead of merging it")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_pack, stream_output=True)

    p = sub.add_parser("prelude", add_help=True,
                       help="adopt the standard dimension declarations "
                            "(an idempotent merge; --show to inspect)")
    p.add_argument("--show", action="store_true",
                   help="print the prelude instead of merging it")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_prelude, stream_output=True)

    p = sub.add_parser("canon", add_help=True,
                       help="print a term's canonical form "
                            "(no term: surface/registry versions)")
    p.add_argument("term", nargs="?")
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_canon, stream_output=True)

    p = sub.add_parser("merge", add_help=True, help="merge a file into the store")
    p.add_argument("file")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("import", add_help=True, help="replace the store with a file")
    p.add_argument("file")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("export", add_help=True, help="write the store to a file")
    p.add_argument("file")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("diff", add_help=True,
                       help="compare this store with another (exit 0/1)")
    p.add_argument("other", help="the file to compare against")
    p.add_argument("categories", nargs="*",
                   help="compare only this query's answer and the categories "
                        "it hangs from")
    p.add_argument("--additions", metavar="PATH",
                   help="also write OTHER's additions to PATH as a store file "
                        "`merge` can apply (removals cannot be in it — see "
                        "the note it prints)")
    p.add_argument("-o", "--output")
    _add_surface_flags(p)
    p.set_defaults(func=cmd_diff, stream_output=True)

    p = sub.add_parser("excerpt", add_help=True,
                       help="write a query's answer to a file")
    # FILE first, because the categories are variadic: with `excerpt CAT... FILE`
    # there is no way to tell the last category from the destination.
    p.add_argument("file")
    p.add_argument("categories", nargs="*")
    p.add_argument("--context", action="store_true",
                   help="include the categories the answers hang from, so the "
                        "file merges (and diffs) into another store that "
                        "shares them")
    p.set_defaults(func=cmd_excerpt)

    p = sub.add_parser("visualize", add_help=True, help="render an image")
    p.add_argument("categories", nargs="*",
                   help="draw just this query's answer (with the query terms "
                        "shown); no categories draws the whole store")
    p.add_argument("--out", help="output filename without extension")
    p.add_argument("--format", default="png", choices=["png", "svg", "pdf"])
    p.set_defaults(func=cmd_visualize)

    p = sub.add_parser("set", add_help=True,
                       help="show settings, or change one")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--force", action="store_true",
                   help="allow `set bee_signer generate` to replace a key that "
                        "is already configured (this strands the old feed)")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("help", add_help=True, help="show help")
    p.set_defaults(func=cmd_help)

    return parser


PARSER = build_parser()


def dispatch(argv, session):
    """Parse one command line and run it. Returns a process-style exit code."""
    if argv and argv[0] == "?":
        # Interactive-prompt sugar for the subsumption test (`? Spaniel
        # Animal`); works from a shell too if you quote the glob character.
        argv = ["below"] + list(argv[1:])
    try:
        args = PARSER.parse_args(argv)
    except SystemExit as exc:  # argparse handled --help or a usage error
        return exc.code or 0

    out = sys.stdout

    handle = None
    outpath = getattr(args, "output", None)
    try:
        if outpath and getattr(args, "stream_output", False):
            handle = open(outpath, "w", encoding="utf-8")
            out = handle
        # A command may return an int to set the exit code (below's
        # true/false is 0/1, grep-style); None keeps the usual 0.
        code = args.func(args, session, out)
        return code or 0
    except (ValueError, OSError) as exc:
        print(f"odag: {exc}", file=sys.stderr)
        return 1
    finally:
        if handle is not None:
            handle.close()

# --------------------------------------------------------------------------- #
# Interactive and batch (stdin) modes
# --------------------------------------------------------------------------- #

def _run_stream(session, stream, interactive):
    if interactive:
        print(f"Ontodag {__version__} - type help for help")
    while True:
        if interactive:
            try:
                line = input("> ")
            except EOFError:
                print()
                break
        else:
            line = stream.readline()
            if not line:
                break
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError as exc:
            print(f"odag: {exc}", file=sys.stderr)
            continue
        if tokens[0] in ("quit", "exit"):
            break
        dispatch(tokens, session)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main(argv=None):
    _force_utf8_streams()
    argv = list(sys.argv[1:] if argv is None else argv)

    # Leading global options: they apply to every command this invocation
    # runs, including a whole stdin batch, and they are the flag layer of the
    # settings table — one option per setting, no exceptions.
    _OVERRIDES.clear()
    valued = {"-f": "store", "--store": "store", "--file": "store",
              "--bee-api": "bee_api", "--bee-batch": "bee_batch",
              "--bee-signer": "bee_signer", "-n": "limit", "--limit": "limit"}
    while argv and (argv[0] in valued or argv[0] in ("--raw", "--render")):
        if argv[0] in ("--raw", "--render"):
            _OVERRIDES["render"] = "on" if argv[0] == "--render" else "off"
            argv = argv[1:]
            continue
        if len(argv) < 2:
            print(f"odag: {argv[0]} requires a value", file=sys.stderr)
            sys.exit(2)
        _OVERRIDES[valued[argv[0]]] = argv[1]
        argv = argv[2:]

    if argv and argv[0] in ("-V", "--version"):
        print(__version__)
        sys.exit(0)
    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(HELP_TEXT)
        sys.exit(0)

    # Constructing a Session does no I/O: the store opens lazily, on the
    # first command that touches it, inside dispatch()'s error contract —
    # so `odag help` works even when the configured store's node is down.
    session = Session(_resolve_store())

    if not argv:
        _run_stream(session, sys.stdin, interactive=sys.stdin.isatty())
        sys.exit(0)

    sys.exit(dispatch(argv, session))


if __name__ == "__main__":
    main()
