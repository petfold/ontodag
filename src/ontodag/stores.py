"""Opening a store the way `odag` does: store specs, backends, and `Store`.

A store spec names where a store lives — a file (`.od`, or `.owl`/`.omn` by
extension), `rs:PATH` (a content-addressed record store on disk) or
`swarm:NAME` — and a backend hides that place behind load()/save(dag)/
describe(). `Store` is what `ontodag.open()` returns and what every `odag`
command works on (the CLI calls it a session): the store for one spec,
opened lazily on first use.

**Public:** `Store` — its `spec`, `as_of`, `dag`, `view()`, `save()`,
`describe()` and `discard()` (docs/REFERENCE.md §5). The backends are how a
Store reaches its storage; they are not promised to anyone outside this
package, so open a Store rather than a backend.

Moved out of the CLI module on 2026-10-09 (the review's question 5): loopmarket
and ontodag-fs opened odag's stores through `ontodag.__main__`'s private
names, which carry no promise and changed without a version saying so. Those
names stay there as aliases of these (`Session` is `Store`), for the releases
still using them.

recordstore and the adapters are imported lazily, inside the backends that
need them, so `import ontodag.stores` and the native path stay dependency-free
(tests/test_boundaries.py B1).
"""

import errno
import os
import socket
import time

from ontodag import native as _native
from ontodag._streams import _err
from ontodag.dag import OntoDAG
from ontodag.settings import (
    OVERRIDES, _abspath, _is_record_store, _is_swarm, configured,
    default_store_path, home_dir, overlay_specs)


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


def _load(path):
    fmt = _detect_format(path)
    if fmt == "native":
        return _native.load(path)
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
        _native.save(dag, path)
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

    def load_at(self, root):
        raise ValueError(
            f"{self.path} is a plain file: it has no versions to read from. "
            f"A store that does:  odag set store rs:"
            f"{os.path.splitext(self.path)[0]}")

    def open_store(self):
        """There is no store here, and therefore no history.

        A `.od` file holds one state: the current one. Undo needs to be able to
        *name* the previous state, which is what a content-addressed store gives
        for free — so this is a tier answer, not a missing feature."""
        raise ValueError(
            f"{self.path} is a plain file: it keeps no version history, so "
            f"there is nothing to undo, redo or list.\n"
            f"  a store that does:  odag set store rs:{os.path.splitext(self.path)[0]}\n"
            f"  (or swarm:NAME to share it — see `odag swarm`)")

    def save(self, dag, message=None):
        # A message labels a state in a store's timeline; a file has neither.
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
    local = default_store_path()
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
    _publish_pointer = None

    def __init__(self, name, store_factory=None, index_store_factory=None,
                 prov_store_factory=None):
        if not name:
            raise ValueError("swarm store needs a name, e.g. swarm:travel")
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
        return os.path.join(home_dir(), self.name + ".root")

    def store_dir(self):
        return os.path.join(home_dir(), self.name + ".store")

    def _legacy_root(self):
        """The head a pre-local-first store (<= 0.14.x) left in NAME.root."""
        try:
            with open(self.pointer_path(), encoding="utf-8") as f:
                return f.read().strip() or None
        except FileNotFoundError:
            return None

    def _has_local_history(self):
        directory = self.store_dir()
        return (os.path.exists(os.path.join(directory, "HEAD"))
                or os.path.exists(os.path.join(directory, "journal.jsonl")))

    def _bootstrap_root(self, pointer):
        """The root a brand-new local store should start from, if any.

        The signed feed first (a followable head is the point of publishing
        one), else the legacy NAME.root file. Only ever consulted for a store
        directory with no history of its own: a replica that has committed
        locally resolves its own HEAD, and a head that moved on elsewhere is
        folded in by `save`'s merge — never adopted as this replica's starting
        point behind its back."""
        if self._has_local_history():
            return None
        if pointer is not None:
            try:
                published = pointer.get()
            except Exception:
                published = None        # offline, or nothing published yet
            if published:
                return published
        return self._legacy_root()

    def _clone_from_swarm(self, store, api, root):
        """Fill a brand-new local store from Swarm, once.

        Seeding the directory's HEAD is NOT enough, and finding that out cost a
        live-node session: `swarmfs`'s `LocalStore.get` heals a missing blob
        only if this replica already *knows* the ref (`_blob_roots`), so a
        scorched-earth replica raises `KeyError` on the very first read. Lazy
        healing recovers evicted blobs; it cannot bootstrap. So a fresh replica
        reads the published root through its own local store in read-through
        mode (swarmfs >= 0.12: blobs it never held are fetched from the node,
        hash-verified, 32 at a time, and not kept) and replays the records into
        itself — after which it owns its blobs and the local store behaves
        normally. Until 2026-10-08 this read went through recordstore's
        `BeeBytesStore`, a second HTTP client; now the client that pushes and
        heals also does the reading.

        Canonical addressing makes this verifiable: replaying the same records
        must commit to the same root. A mismatch means the network served
        something other than what the pointer promised, which is worth saying
        out loud rather than adopting silently."""
        from recordstore import RecordStore
        local = store.local
        if not hasattr(local, "read_through"):
            raise ValueError(
                f"reading the published {self.name} store needs swarmfs "
                "0.12.0 or later (read-through); upgrade with:  "
                "pip install -U \"ontodag[swarm]\"")
        local.read_through = True
        try:
            source = RecordStore.at(root, local)
            for key, record in source.items():
                store.put(key, record)
        finally:
            local.read_through = False
        cloned = store.commit()
        if cloned != root:
            print(f"odag: warning: cloned {self.name} from {root[:12]}… but the "
                  f"records commit to {cloned[:12]}… — the node served "
                  f"different content than the feed points at", file=_err())

    def _record_store(self):
        # BeeRemote resolves this order itself, but being explicit keeps
        # `describe`/errors honest about which endpoint is in play
        api = configured("bee_api") or os.environ.get(
            "BEE_API_URL", "http://localhost:1633")
        # "auto" (ask the node for a usable batch) is this call site's default,
        # not the setting's: `set bee_batch` showing "auto" would misreport an
        # unconfigured batch as a configured one.
        batch = configured("bee_batch") or "auto"
        signer = configured("bee_signer")
        try:
            if self._store_factory is not None:
                return self._store_factory()
            from recordstore import local_first_store
            os.makedirs(home_dir(), exist_ok=True)
            publish_pointer = None
            if signer:
                from recordstore import SwarmFeedPointer
                publish_pointer = SwarmFeedPointer(
                    api, self.name, signer=signer, postage_batch_id=batch)
            self._publish_pointer = publish_pointer
            # Asked before opening (the answer depends on the directory being
            # untouched), used after (cloning needs an open store).
            bootstrap = self._bootstrap_root(publish_pointer)
            # Transient windows may overlap for a moment (odag saving while
            # an odag-fs mount rehydrates): the writer lock is only ever
            # held briefly, so a short retry absorbs it.
            deadline = time.monotonic() + _LOCK_RETRY
            while True:
                try:
                    store = local_first_store(self.store_dir(), api,
                                              stamp=batch,
                                              publish_pointer=publish_pointer)
                    break
                except Exception as exc:
                    if type(exc).__name__ != "StoreLocked" or \
                            time.monotonic() > deadline:
                        raise
                    time.sleep(0.2)
            if bootstrap and getattr(store, "root", None) is None:
                self._clone_from_swarm(store, api, bootstrap)
            return store
        except ImportError as exc:
            missing = exc.name or "swarmfs"
            raise ValueError(
                f"the swarm backend needs an optional dependency that is not "
                f"installed ({missing!r}); install the swarm extra with:  "
                f"pip install \"ontodag[swarm]\"   "
                f"(that covers the local-first store machinery — swarmfs — "
                f"plus coincurve for signing feed updates)"
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
            raise _swarm_open_error(self.name, configured("bee_api"),
                                    exc) from exc
        finally:
            # transient window: the in-memory DAG serves the session;
            # save() reopens and rebinds. (No-op for factory test stores.)
            close = getattr(store, "close", None)
            if close is not None:
                close()

    def open_store(self):
        """A store handle for history operations (a transient window, as ever)."""
        return self._record_store()

    def load_at(self, root):
        return _load_at_root(self, root)

    def publish_head(self, store):
        """After a HEAD move, point the feed at it too.

        Publication normally rides a confirmation event, and moving HEAD
        backwards produces none — so without this an undo would be invisible to
        anyone following the feed, which is a silent disagreement between what
        this replica shows and what it publishes."""
        pointer = self._publish_pointer
        publish = getattr(store, "publish", None)
        if pointer is None or publish is None:
            return None
        return publish(pointer)

    def save(self, dag, message=None):
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
                dag.commit(message=message)  # local, instant, offline-safe
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
                        file=_err(),
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
        self._key = None                   # resolved on first open

    def _encryption_key(self):
        """The store's encryption key, or None for a plaintext store.

        **The marker in the store decides; the setting only supplies key
        material.** An existing encrypted store refuses to open without
        the right `store_key` (wrong key refuses at open — never garbage);
        an existing plaintext store stays plaintext even when a key is
        configured (so a public overlay can sit beside an encrypted
        primary under one setting); a NEW store is created encrypted iff
        `store_key` is set at creation time. The index and provenance
        siblings inherit the decision — audience is contagious along
        derivation (PROJECTIONS.md §11)."""
        from ontodag import encstore
        secret = configured("store_key")
        marker = encstore.read_marker(self.path)
        if marker is not None:
            if not secret:
                raise ValueError(
                    f"{self.describe()} is encrypted — set store_key "
                    f"(odag set store_key ..., $ONTODAG_STORE_KEY, or "
                    f"--store-key) to open it")
            key = encstore.derive_key(secret)
            encstore.check_key(marker, key, self.describe())
            return key
        exists = (os.path.exists(os.path.join(self.path, "root"))
                  or os.path.isdir(os.path.join(self.path, "blobs")))
        if secret and not exists:
            key = encstore.derive_key(secret)
            encstore.write_marker(self.path, key)
            return key
        return None

    def _store_at(self, directory):
        from ontodag._extras import require
        rs = require("recordstore", "store", "a local record store (rs:)")
        os.makedirs(directory, exist_ok=True)
        if self._key is None:
            self._key = self._encryption_key() or False
        blobs = rs.DirBytesStore(os.path.join(directory, "blobs"))
        if self._key:
            from ontodag.encstore import EncryptedBytesStore
            blobs = EncryptedBytesStore(blobs, self._key)
        return rs.RecordStore(
            blobs,
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

    def open_store(self):
        return self._record_store()

    def load_at(self, root):
        return _load_at_root(self, root)

    def save(self, dag, message=None):
        dag.commit(message=message)

    def describe(self):
        return f"rs:{self.path}"


def _load_at_root(backend, root):
    """Hydrate a read-only DAG at `root`, inside one transient window.

    `RecordStore.at` is a *view* over the same blobs, so the window can close
    the moment hydration is done: an EagerOntoDAG holds the whole state in
    memory, which is exactly what makes reading a past version cost nothing
    afterwards. `root` may be any unambiguous prefix of one the timeline knows
    — `odag history` prints twelve characters, so demanding sixty-four would
    make the feature unusable with the only thing that shows you roots."""
    from ontodag.eager import EagerOntoDAG
    from recordstore import RecordStore

    store = backend.open_store()
    close = getattr(store, "close", None)
    try:
        resolved = _resolve_root(store, root)
        return EagerOntoDAG(RecordStore.at(resolved, store.blobs))
    finally:
        if close is not None:
            close()


def _resolve_root(store, root):
    """A full root from a prefix, or a teaching error naming the ambiguity."""
    known = [version.root for version in store.history()]
    if root in known:
        return root
    matches = sorted({name for name in known if name.startswith(root)})
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(
            f"{root}: not a version this store has been at "
            f"(odag history lists them)")
    raise ValueError(
        f"{root}: ambiguous — matches {', '.join(name[:16] for name in matches)}")


def make_backend(spec):
    if _is_swarm(spec):
        return SwarmBackend(spec[len("swarm:"):])
    if _is_record_store(spec):
        return LocalRecordBackend(spec[len("rs:"):])
    return FileBackend(spec)


# --------------------------------------------------------------------------- #
# The store, as a program holds it (odag's session)
# --------------------------------------------------------------------------- #

class Store:
    """The store a spec names, opened lazily on first use.

    `spec` is a normalized store spec (`ontodag.open` and
    `settings.resolve_store` normalize; this class takes what it is given).
    `as_of` reads a past version instead — any prefix of a root `odag
    history` shows — and makes the store read-only. When it is not given,
    the flag layer's `as_of` applies (odag's `--as-of`).

    Opening is I/O — for a `swarm:` spec, network I/O — so it belongs to
    the commands that touch the store, where dispatch()'s error contract
    already applies. Commands that never do (`help`, bare `canon`,
    `set KEY VALUE`, `prelude --show`, `swarm`) must work with the node
    down: a user whose node is unreachable and who types `odag help` to
    find the way out has to get help, not the error they came to fix. For
    a program the same rule means: constructing a Store never fails on the
    store; its first `dag` (or `view()`) does, with odag's message."""

    # A class default as well, for a session assembled without the
    # constructor (`Session.__new__` and attributes, as tests wire an
    # in-memory backend), which predates `as_of`.
    as_of = None

    def __init__(self, spec, as_of=None):
        self.spec = spec
        self.as_of = as_of
        self._backend = None
        self._dag = None
        self._view = None
        self._view_specs = None

    def __repr__(self):
        past = f", as_of={self.as_of!r}" if self.as_of else ""
        return f"Store({self.spec!r}{past})"

    def _past(self):
        return self.as_of or OVERRIDES.get("as_of")

    def _load(self):
        backend = make_backend(self.spec)
        as_of = self._past()
        dag = backend.load_at(as_of) if as_of else backend.load()
        self._backend, self._dag = backend, dag
        self._loaded = getattr(dag, "_version", None)
        self._view = None

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

    def discard(self):
        """Forget the store as held in memory, so the next use reads it
        again: whatever a refused command changed and never saved goes with
        it, instead of riding out on the next command's save."""
        self._dag = None
        self._view = None

    def switch(self, spec):
        # Atomic, and deliberately EAGER: build and load first, assign only
        # once nothing can fail. A store that won't open (node down) must
        # leave the session on the one it already had, not half-switched to
        # a backend whose load failed — and `set store` validating at set
        # time is the feature.
        backend = make_backend(spec)
        dag = backend.load()
        # A local-first store holds a writer lock and a sync thread; release
        # them when the session moves on (switching back to the same store
        # in one session would otherwise hit its own lock).
        old = getattr(self._dag, "store", None)
        self.spec, self._backend, self._dag = spec, backend, dag
        self._loaded = getattr(dag, "_version", None)
        self._view = None
        close = getattr(old, "close", None)
        if close is not None:
            close()

    def view(self):
        """The composed READ view: this store with every configured overlay
        merged in — the join of `docs/plans/PROJECTIONS.md` §5.

        Overlays are regenerable machine layers (projections) or reference
        stores consulted alongside your own; composing them at read time is
        what lets `get photo vienna sys:on:drive-budapest` cross the layers
        while nothing ever writes the union anywhere. The routing rule is the
        excerpt/visualize asymmetry once more: **anything that answers or
        draws reads the view; anything that produces a mergeable artifact or
        mutates reads the primary** — an export of the composed view would
        launder machine claims into a human store on the next import.

        The composed object is a plain in-memory OntoDAG: it has no store and
        no commit, so committing the union is not refused but *impossible*.
        Each layer keeps its own reduction; the composition re-reduces in
        memory via merge (I7), and query results are identical either way
        because cones are reduction-invariant. Cached per session; every
        rebinding of the primary (`_load`, `switch`) and every mutation
        (`save`) invalidates it, and a changed `overlays` setting is caught
        by comparing specs."""
        specs = overlay_specs()
        if not specs:
            return self.dag
        if self._view is None or self._view_specs != specs:
            composed = OntoDAG()
            composed.merge(self.dag)
            for spec in specs:
                composed.merge(make_backend(spec).load())
            self._view, self._view_specs = composed, specs
        return self._view

    def save(self, message=None):
        """Write the DAG back: a commit for `rs:`/`swarm:` stores, labelled
        `message` in the store's history (odag's `-m` when not given); the
        file for a file store, which keeps no labels."""
        # A past state is a state, not a place to write from: the pointer is
        # elsewhere, so a commit here would either be ignored or silently
        # fork. `undo`/`redo` are how the store *moves*.
        if self._past():
            raise ValueError(
                "--as-of opens a past version read-only; nothing can be "
                "written to it.\n"
                "  to make the store go back there:  odag undo  (or `redo`)")
        if message is None:
            message = OVERRIDES.get("message")
        self.backend.save(self.dag, message=message)
        self._view = None

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
        self.dag.clear()
        self.dag.merge(incoming)
        self.save()
