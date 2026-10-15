"""Running OntoDAG in a browser, against Swarm.

**Status (2026-10-13):** the page in `demo/freedom/` runs this under
Pyodide, reading published packs from Swarm through the page's JavaScript
(`demo/freedom/swarm.js`), with `run_sync` (JSPI) as the bridge or by
retrying where JSPI cannot suspend Python. Your own store (`LocalStore`)
lives in a local file and is published through a node (`StagedBlobs`,
`demo/freedom/publish.js`; docs/plans/BROWSER.md §16). The organiser
page shows it with the packs beside it (`Organiser`, §17). The adapters' logic
is also covered by tests with a fake bridge; the packaging constraints
are checked in `tests/test_boundaries.py`.

## Why this can work at all

`recordstore` names two seams, and they are two methods each:

    BytesStore:  put(bytes) -> ref      get(ref) -> bytes
    Pointer:     get() -> ref | None    set(ref) -> None

Everything above them — the trie, canonical roots, snapshots, proofs, the
whole of OntoDAG — is pure Python with no filesystem and no sockets. So
"OntoDAG in a browser on Swarm" needs no fork and no special build: it needs
an implementation of those four methods that talks to a Bee node through
JavaScript. That is what this module is.

## The one real obstacle: sync over async

`BytesStore.put`/`get` are synchronous, and every browser API for reaching
the network is asynchronous. Python cannot block on a JavaScript promise
from the main thread — the event loop that would resolve it is the one being
blocked. This is not a Pyodide quirk; it is the shape of the platform.

Two ways out, and the caller picks:

1. **A web worker with `SharedArrayBuffer`.** Run Python in a worker and let
   it block on `Atomics.wait` while the main thread does the fetching. Needs
   cross-origin isolation headers (`COOP`/`COEP`) on whatever serves the
   page — the usual reason this is annoying to deploy.
2. **JSPI** (`pyodide.ffi.run_sync`). Newer Pyodide on browsers with the
   JavaScript Promise Integration proposal can suspend a synchronous Python
   call across an await. Cleaner, and requires no headers, but the support
   matrix is narrower.

Rather than choose, this module takes a **bridge**: any callable that runs a
JS async function and returns its result synchronously. Supply the one your
deployment can support. `run_sync` from `pyodide.ffi` satisfies it directly.

3. **Retry** (`bridge=RETRY`). Where neither works, Python never waits: it
   reads only blobs the page already holds (`js_store.cached(ref)`), and a
   missing one stops the call with `NeedBlobs`, naming every blob it lacked.
   The page fetches them and runs the call again (`RetryingPage`), on a
   fresh reader, so a run cut short leaves nothing behind. Pyodide on iOS
   needs this: there CPython calls function pointers through a JavaScript
   trampoline, and JSPI cannot suspend across a JavaScript frame.

## Deliberately not bee-js specific

The store talks to a small duck-typed JS object with `upload` and `download`,
so it works with bee-js, a `fetch` wrapper against a Bee HTTP endpoint, a
gateway, or an in-page node if one exists. The Swarm side of the browser
story is moving; the adapter should not have to move with it.
"""


class BlobUnreachable(OSError):
    """A blob the JavaScript side could not produce: not retrievable, or
    refused because its chunks did not match their addresses. An `OSError`,
    never a `KeyError`: recordstore turns it into `RecordUnavailable`, so a
    lazy reader fails loudly instead of taking a category for absent."""


RETRY = "retry"
"""The bridge that never waits: see `NeedBlobs` and `RetryingPage`."""


class NeedBlobs(BaseException):
    """A call in retry mode reached blobs the page does not hold yet. A
    BaseException, so no `except Exception` on the way out (recordstore's,
    the reader's) mistakes it for a failure: it is an instruction to fetch
    `refs` and run the call again."""

    def __init__(self, refs):
        self.refs = list(refs)
        super().__init__(f"{len(self.refs)} blob(s) to fetch")


class JsBytesStore:
    """A `recordstore` BytesStore backed by a JavaScript object.

    `js_store` must provide:

        upload(data: Uint8Array) -> Promise<string>   # returns the reference
        download(ref: string)    -> Promise<Uint8Array>

    `bridge` turns a returned promise into a value synchronously; see the
    module docstring for what can implement it. With `bridge=RETRY` the
    store reads `js_store.cached(ref)` instead (the blob, `undefined` if the
    page has not fetched it, or a throw if fetching it failed), and raises
    `NeedBlobs` for what is missing.

    Nothing here imports `recordstore` — the protocol is structural, which is
    the same one-directional boundary the rest of the package keeps (B2).
    """

    def __init__(self, js_store, bridge, encoding="utf-8"):
        self._js = js_store
        self._bridge = bridge
        self._encoding = encoding

    def put(self, data: bytes) -> str:
        ref = self._bridge(self._js.upload(self._to_js(data)))
        # bee-js hands back a Reference object in some versions and a plain
        # string in others; both stringify to the hex reference, and a ref is
        # only ever compared and used as a dict key.
        return str(ref)

    def get(self, ref: str) -> bytes:
        if self._bridge == RETRY:
            value = self._cached(str(ref))
            if value is None:
                raise NeedBlobs([str(ref)])
            return value
        try:
            return self._to_bytes(self._bridge(self._js.download(str(ref))))
        except Exception as e:
            raise BlobUnreachable(f"blob {str(ref)[:16]}…: {e}") from e

    def _cached(self, ref):
        try:
            value = self._js.cached(ref)
        except Exception as e:
            raise BlobUnreachable(f"blob {ref[:16]}…: {e}") from e
        return None if value is None else self._to_bytes(value)

    def get_many(self, refs):
        """Several blobs in one call, read concurrently on the JS side when
        it offers `downloadMany(refs)`; one at a time otherwise."""
        refs = [str(r) for r in refs]
        if self._bridge == RETRY:
            values = {r: self._cached(r) for r in refs}
            missing = [r for r, v in values.items() if v is None]
            if missing:
                raise NeedBlobs(missing)
            return values
        many = getattr(self._js, "downloadMany", None)
        if many is None:
            return {r: self.get(r) for r in refs}
        try:
            values = self._bridge(many(self._to_js(refs)))
        except Exception as e:
            raise BlobUnreachable(f"{len(refs)} blobs: {e}") from e
        values = list(values.to_py() if hasattr(values, "to_py") else values)
        return {r: self._to_bytes(v) for r, v in zip(refs, values)}

    # -- the JS <-> Python edge, kept in one place -------------------------- #

    @staticmethod
    def _to_js(data: bytes):
        try:
            from pyodide.ffi import to_js            # type: ignore
        except ImportError:
            return data                              # a test double, or Node
        return to_js(data)

    @staticmethod
    def _to_bytes(value) -> bytes:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        to_py = getattr(value, "to_py", None)        # a JS typed array
        return bytes(to_py() if callable(to_py) else value)


class JsFeedPointer:
    """A `recordstore` Pointer over a Swarm feed, through JavaScript.

    `js_feed` must provide:

        read()            -> Promise<string | null>
        write(ref: string) -> Promise<any>

    The same shape as `SwarmFeedPointer` on the Python side: the mutable
    "latest root" that makes a store followable, rather than a bag of
    immutable blobs. A browser that can only read passes a feed whose
    `write` rejects — `set` will then raise, which is the honest outcome.
    """

    def __init__(self, js_feed, bridge):
        self._js = js_feed
        self._bridge = bridge

    def get(self):
        ref = self._bridge(self._js.read())
        return str(ref) if ref else None

    def set(self, root) -> None:
        self._bridge(self._js.write(str(root)))


class StagedBlobs:
    """The blobs a publish writes, held by the page until it uploads them,
    over the blobs it reads from Swarm.

    `stage` is the page's object (publish.js `Stage`): `put(data)` computes
    the blob's Swarm reference for a plain upload, keeps the bytes and
    returns the reference; `get(ref)` hands kept bytes back, or nothing.
    Both answer at once, so writing needs no bridge, in retry mode either.
    Reads of anything not kept go to `reader` (a `JsBytesStore`)."""

    def __init__(self, stage, reader):
        self._stage = stage
        self._reader = reader

    def put(self, data: bytes) -> str:
        return str(self._stage.put(JsBytesStore._to_js(bytes(data))))

    def _kept(self, ref):
        value = self._stage.get(ref)
        return None if value is None else JsBytesStore._to_bytes(value)

    def get(self, ref: str) -> bytes:
        ref = str(ref)
        kept = self._kept(ref)
        return kept if kept is not None else self._reader.get(ref)

    def get_many(self, refs):
        refs = [str(r) for r in refs]
        out = {r: self._kept(r) for r in refs}
        missing = [r for r, v in out.items() if v is None]
        if missing:
            many = getattr(self._reader, "get_many", None)
            fetched = many(missing) if many else {r: self._reader.get(r) for r in missing}
            out.update(fetched)
        return out


class LocalStorageBytesStore:
    """A BytesStore over `window.localStorage` (or any dict-like JS object).

    Not a Swarm client — a way to have a *working, persistent* DAG in a
    browser tab with no node, no network and no async problem at all, since
    localStorage is synchronous. The same role `rs:PATH` plays on the
    command line: canonical roots and snapshots first, distribution later.

    Blobs are stored base64-encoded under a key prefix, because localStorage
    holds strings.
    """

    def __init__(self, storage, prefix="ontodag:", addressing=None):
        self._storage = storage
        self._prefix = prefix
        # Default addressing matches recordstore's MemoryBytesStore/
        # DirBytesStore (sha256), so roots stay comparable with a store
        # written on a laptop.
        self._ref_of = addressing or self._sha256

    @staticmethod
    def _sha256(data: bytes) -> str:
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def put(self, data: bytes) -> str:
        import base64
        ref = self._ref_of(data)
        self._storage.setItem(self._prefix + ref,
                              base64.b64encode(data).decode("ascii"))
        return ref

    def get(self, ref: str) -> bytes:
        import base64
        value = self._storage.getItem(self._prefix + str(ref))
        if value is None:
            raise KeyError(ref)
        return base64.b64decode(value)


def open_published(root, js_store, bridge=None, prefetch=True, index_root=None):
    """A read-only `LazyOntoDAG` over the store published at `root`, its
    blobs read through `js_store` (`download`, `downloadMany`). `bridge`
    defaults to Pyodide's `run_sync`, which needs JSPI and a call that
    entered Python asynchronously (`runPythonAsync`, `callPromising`);
    `RETRY` reads only what the page holds (see `RetryingPage`).
    With `prefetch`, a walk reads each level's records in one batch when
    recordstore can (`RecordStore.get_many`). `index_root` names the store's
    published cone summaries (`ontodag.cones`): a broad category's cone is
    then one record instead of a walk; an index for another root, or from
    another registry version, is ignored."""
    from recordstore import RecordStore
    from ontodag.lazy import LazyOntoDAG
    if bridge is None:
        from pyodide.ffi import run_sync        # type: ignore
        bridge = run_sync
    blobs = JsBytesStore(js_store, bridge)
    cone_index = None
    if index_root:
        cone_index = _CacheOnly(lambda: _cone_index(RecordStore.at(index_root, blobs), root))
    return LazyOntoDAG(RecordStore.at(root, blobs), prefetch=prefetch,
                       cone_index=cone_index)


def _cone_index(store, root):
    from ontodag.cones import ConeIndex
    return ConeIndex(store, root)


class _CacheOnly:
    """A cone index read as the cache it is: one that cannot be fetched
    answers "not summarized", and the reader walks the cone instead (exact,
    and failing loudly itself if the data cannot be fetched either)."""

    def __init__(self, open_index):
        self._open = open_index
        self._index = None
        self._dead = False
        self.error = None           # why the index went unused, if it did

    def cone(self, name):
        if self._dead:
            return None
        try:
            if self._index is None:
                self._index = self._open()
            return self._index.cone(name)
        except Exception as e:
            self._dead = True
            self.error = f"{type(e).__name__}: {e}"
            return None


class RetryingPage:
    """The page's calls in retry mode. `make()` builds the answering object
    (a `PageReader` over `open_published(..., bridge=RETRY)`, say);
    `call(method, *args)` answers as that method does, or, when the run
    reached blobs the page has not fetched, `{"need": [refs]}`: the page
    fetches them and calls again. A run cut short discards the object, so
    the next one starts fresh and no half-read state survives (the fetched
    blobs stay with the page, so it is read again without the network)."""

    def __init__(self, make):
        self._make = make
        self._target = None

    def call(self, method, *args):
        import json
        try:
            if self._target is None:
                self._target = self._make()
            return getattr(self._target, method)(*args)
        except NeedBlobs as need:
            self._target = None
            return json.dumps({"need": need.refs})


def needing(method, *args):
    """`method(*args)`'s answer, or in retry mode `{"need": [refs]}` when it
    stopped for blobs the page has not fetched: for calls on an object that
    must be kept (your own store), which change nothing before their last
    read, so the page fetches and simply calls again."""
    import json
    try:
        return method(*args)
    except NeedBlobs as need:
        return json.dumps({"need": need.refs})


class PageReader:
    """What the read-only page asks of a published store, answered as JSON
    text, so nothing but strings crosses into JavaScript.

    `node(name)` is a category with what lies above and below it, each child
    with how many categories are under it (their records read in one batch);
    `get(query)` is a query's answer; `below(a, b)` is `is_below`. Names are
    the store's canonical names. Every answer carries the reader's running
    counts: records read and round trips taken."""

    def __init__(self, dag, limit=100):
        self.dag = dag
        self.limit = limit

    def _answer(self, **fields):
        import json
        fetches = getattr(self.dag, "fetches", 0)
        fields["records"] = fetches
        fields["round_trips"] = getattr(self.dag, "rounds", fetches)
        return json.dumps(fields)

    def node(self, name=None):
        dag = self.dag
        root = dag.root.name
        name = root if not name else name
        node = dag.nodes.get(name)
        if node is None:
            return self._answer(name=name, found=False)
        children = sorted(node.neighbors, key=lambda c: c.name)
        shown = children[:self.limit]
        expand_many = getattr(dag, "_expand_many", None)
        if expand_many is not None:
            expand_many(shown)
        above = sorted(p.name for p in node.parents
                       if dag.nodes.get(p.name) is p and p.name != root)
        return self._answer(
            name=name, found=True, top=name == root,
            count=node.descendant_count, above=above,
            below=[[c.name, c.descendant_count] for c in shown],
            more=len(children) - len(shown))

    def get(self, query):
        import shlex
        try:
            terms = shlex.split(query)
        except ValueError as e:
            return self._answer(query=query, error=str(e))
        try:
            answer = sorted(item.name for item in self.dag.get(terms))
        except ValueError as e:
            return self._answer(query=query, error=str(e))
        return self._answer(query=query, count=len(answer),
                            names=answer[:self.limit],
                            more=max(0, len(answer) - self.limit))

    def below(self, a, b):
        try:
            return self._answer(a=a, b=b, below=bool(self.dag.is_below(a, b)))
        except ValueError as e:
            return self._answer(a=a, b=b, error=str(e))



class LocalStore(PageReader):
    """The page's own store: a whole `OntoDAG` in memory, read from and saved
    to a `.od` file on the person's computer (the page's JavaScript does the
    file handling). The text is the native format, so the same file works
    with `odag`. `publish` writes it to Swarm as `odag -f swarm:NAME` would,
    and `fetch` brings in what a feed holds.

    It answers like `PageReader` (`node`, `get`, `below`) and adds the
    writes, each answered as JSON with `changed` (unsaved changes) and
    `count` (categories in the store): `put` and `remove` as `odag put` and
    `odag remove` do them, and `prelude` as `odag prelude`. Typed input is
    the person's: relative times are read with the clock (`now`, unix
    seconds), as at the `odag` command; the core canonicalizes the rest."""

    def __init__(self, dag=None, name="store.od", now=None):
        from ontodag import OntoDAG
        super().__init__(dag if dag is not None else OntoDAG())
        self.name = name
        self.changed = False
        self._now = now

    @classmethod
    def from_text(cls, text, name="store.od", now=None):
        """A store from a `.od` file's text (`ontodag.native.loads`)."""
        from ontodag import native
        return cls(native.loads(text, source=name), name=name, now=now)

    def _clock(self):
        if self._now is not None:
            return self._now
        import time
        return time.time()

    def _typed(self, name):
        from ontodag import surface
        return surface.absolute(name, self.dag, self._clock())

    def summary(self):
        return self._answer(name=self.name, changed=self.changed,
                            count=len(self.dag.nodes) - 1)

    def put(self, item, parents=""):
        """File `item` under the categories named in `parents` (space
        separated, quoted as in a shell), or at the top with none."""
        import shlex
        try:
            names = [self._typed(p) for p in shlex.split(parents)]
            item = self._typed(item.strip())
            if not item:
                raise ValueError("name what to put")
            missing = [p for p in names
                       if p not in self.dag.nodes and not self.dag.is_term(p)]
            if missing:
                raise ValueError(
                    f"unknown super-categor{'y' if len(missing) == 1 else 'ies'}: "
                    f"{', '.join(missing)} (put {'it' if len(missing) == 1 else 'them'} first)")
            self.dag.put(item, names)
        except ValueError as e:
            return self._answer(error=str(e), changed=self.changed,
                                count=len(self.dag.nodes) - 1)
        self.changed = True
        return self._answer(put=item, under=names, changed=True,
                            count=len(self.dag.nodes) - 1)

    def remove(self, names):
        """Remove categories by contraction, as `odag remove` does: what is
        below each one moves up to its parents, so nothing below is lost."""
        import shlex
        try:
            items = shlex.split(names)
            if not items:
                raise ValueError("name what to remove")
            gone, _moves = self.dag.removal_plan(items)
            self.dag.remove_many(items)
        except (ValueError, KeyError) as e:
            return self._answer(error=str(e).strip("'\""), changed=self.changed,
                                count=len(self.dag.nodes) - 1)
        self.changed = True
        return self._answer(removed=sorted(gone), changed=True,
                            count=len(self.dag.nodes) - 1)

    def prelude(self):
        """Adopt the standard declarations (typed values), `odag prelude`."""
        from ontodag import prelude
        before = len(self.dag.nodes)
        prelude.apply(self.dag)
        added = len(self.dag.nodes) - before
        self.changed = self.changed or added > 0
        return self._answer(added=added, changed=self.changed,
                            count=len(self.dag.nodes) - 1)

    def text(self):
        """The store as `.od` text, to save."""
        from ontodag import native
        return native.dumps(self.dag)

    def saved(self, name=None):
        """The page wrote `text()` to a file (named `name`, if it changed)."""
        if name:
            self.name = name
        self.changed = False
        return self.summary()

    # -- on Swarm ----------------------------------------------------------- #
    #
    # `blobs` is a `StagedBlobs`: what a commit writes is staged for the page
    # to upload, and what a fold reads comes from Swarm. A store published or
    # fetched in this session is an `EagerOntoDAG` whose `base_root` is the
    # root it descends from; one from a file, or a new one, descends from
    # nothing published.

    def _lineage(self):
        from ontodag.eager import EagerOntoDAG
        return self.dag.base_root if isinstance(self.dag, EagerOntoDAG) else None

    def _read_first(self, feed_root, blobs):
        """Read everything folding `feed_root` in will read, before anything
        changes. In retry mode a blob the page lacks stops the call here
        (`NeedBlobs`) with the store as it was, and the run after the fetch
        finds every blob it needs."""
        from recordstore import RecordStore
        base = self._lineage()
        if base is None:
            for _ in RecordStore.at(feed_root, blobs).items():
                pass
        else:
            for _ in RecordStore.at(base, blobs).diff(feed_root):
                pass

    def _folded(self, feed_root, blobs):
        """This store with what `feed_root` holds folded in, as `odag`'s save
        folds a moved head: the union of both sides (so a removal made here
        comes back if the feed still has it), read from the divergence when
        this store descends from a published root. The result is an
        `EagerOntoDAG` whose store is at `feed_root`, so a commit lands on
        it."""
        from recordstore import RecordStore
        from ontodag.eager import EagerOntoDAG
        if self._lineage() is None:
            dag = EagerOntoDAG(RecordStore(blobs, root=feed_root))
            dag.merge(self.dag)
            return dag
        dag = self.dag
        dag.store = RecordStore(blobs, root=feed_root)
        dag.merge_published(feed_root, bytes_store=blobs)
        return dag

    def _took(self, dag, names, text):
        """The names a fold brought in; a fold that changed the store at all
        leaves its file out of date (`changed`)."""
        from ontodag import native
        came_in = sorted(set(dag.nodes) - names)
        if native.dumps(dag) != text:
            self.changed = True
        return came_in

    def publish(self, feed_root, blobs):
        """Commit this store for its feed, as `odag -f swarm:NAME` saves it.
        `feed_root` is the feed's newest root ("" for an empty feed). When the
        feed holds what this store descends from, or nothing, the store is
        committed as it is, removals included; when the feed moved on (written
        elsewhere, or this store came from a file), it is folded in first.

        Answers the new `root`, whether the feed was folded in (`merged`) and
        the names that came from it (`came_in`). The page then uploads what
        `blobs` staged and points the feed at `root`."""
        from recordstore import RecordStore
        from ontodag import native
        from ontodag.eager import EagerOntoDAG
        if len(self.dag.nodes) <= 1:
            return self._answer(error="the store is empty: put something in it first",
                                changed=self.changed, count=0)
        feed_root = feed_root or None
        base = self._lineage()
        moved = feed_root is not None and feed_root != base
        came_in = []
        if moved:
            self._read_first(feed_root, blobs)
            names, text = set(self.dag.nodes), native.dumps(self.dag)
            dag = self._folded(feed_root, blobs)
            came_in = self._took(dag, names, text)
        elif base is not None:
            dag = self.dag
            dag.store = RecordStore(blobs, root=base)
        else:
            dag = EagerOntoDAG(RecordStore(blobs))
            dag.merge(self.dag)
        root = dag.commit()
        self.dag = dag
        return self._answer(root=root, merged=moved, came_in=came_in[:self.limit],
                            more=max(0, len(came_in) - self.limit),
                            changed=self.changed, count=len(dag.nodes) - 1)

    def fetch(self, feed_root, blobs):
        """Bring in what the feed's newest root holds, folded as `publish`
        folds it, writing nothing: a store published from another device
        or from `odag`, into this one. A new store becomes exactly the
        published one."""
        if not feed_root:
            return self._answer(error="nothing is published under this name and key yet",
                                changed=self.changed, count=len(self.dag.nodes) - 1)
        from ontodag import native
        came_in = []
        if feed_root != self._lineage():
            self._read_first(feed_root, blobs)
            names, text = set(self.dag.nodes), native.dumps(self.dag)
            dag = self._folded(feed_root, blobs)
            dag.base_root = feed_root     # its records now describe feed_root
            came_in = self._took(dag, names, text)
            self.dag = dag
        return self._answer(fetched=feed_root, came_in=came_in[:self.limit],
                            more=max(0, len(came_in) - self.limit),
                            changed=self.changed, count=len(self.dag.nodes) - 1)


def capture_of(size, ranges):
    """When and where a photo or a video was taken (`ontodag.capture`), for
    the page, which holds `ranges` ([(offset, bytes)]) of a file of `size`
    bytes while it hashes it: JSON {time, geo}, or {more: [offset, size]}
    for bytes it must hand in as well."""
    import json
    from ontodag import capture
    try:
        found = capture.from_ranges(ranges, size)
    except capture.NeedBytes as need:
        return json.dumps({"more": [need.offset, need.size]})
    return json.dumps({"time": found.time, "geo": found.geo})


class Organiser:
    """Your store with the vocabularies shown beside it: the organiser page
    (docs/plans/BROWSER.md §17).

    Answers read the composed view, your store merged with the packs shown
    (and the packs they presume), as `odag`'s overlays are composed; writes
    go to your store alone. A category taken from a vocabulary enters your
    store as a name only (question 39): the vocabulary shown supplies its
    places. `texts` maps each pack to its canonical `.od` text, which the
    page ships beside itself: loading text is ten times quicker than
    building a pack from `ontodag.packs`.

    Every answer is JSON text, as `PageReader`'s are."""

    def __init__(self, mine, texts, limit=100):
        self.mine = mine
        self.texts = dict(texts)
        self.limit = limit
        self.shown = []
        self._read = None
        self._vocab = None
        self._unions = {}
        self._view = None
        self.folder = None        # the last look at files (`files_look`)
        self._declined = set()    # (version, document) pairs undone this session

    def _answer(self, **fields):
        import json
        return json.dumps(fields)

    @property
    def vocab(self):
        if self._vocab is None:
            from ontodag.suggest import Vocabularies
            self._vocab = Vocabularies(self.texts)
        return self._vocab

    def use(self, mine):
        """Another store of yours (new, opened, or fetched)."""
        self.mine = mine
        self._view = None
        self.folder = None
        self._declined = set()

    # -- what is shown ---------------------------------------------------- #

    def _closure(self):
        """The packs shown and those they presume, in merge order."""
        if self._read is None:
            self._read = self._presumed()
        return self._read

    def _presumed(self):
        from ontodag import packs
        names = set(self.shown)
        for p in list(names):
            if packs.presumes_core(p):
                names.add("core")
        for p in list(names):
            if packs.presumes_prelude(p):
                names.add("prelude")
        first = [p for p in ("prelude", "core") if p in names]
        return first + sorted(names - set(first))

    def show(self, names):
        """Show these packs beside your store (a list of pack names)."""
        unknown = [n for n in names if n not in self.texts]
        if unknown:
            return self._answer(error=f"no such vocabulary: {', '.join(unknown)}", shown=self.shown)
        self.shown = sorted(set(names))
        self._read = None
        self._view = None
        return self._answer(shown=self.shown, read=self._closure())

    def uses(self):
        """The packs your store takes names from, which the page shows
        unless the person turned them off."""
        mine = self._names()
        found = set()
        for name in mine:
            found.update(self.vocab.packs_having(name))
        return self._answer(packs=sorted(found - {"prelude"}))

    def _union(self):
        from ontodag import OntoDAG, native
        closure = tuple(self._closure())
        if closure not in self._unions:
            dag = OntoDAG()
            for p in closure:
                dag.merge(native.loads(self.texts[p], source=p))
            self._unions[closure] = native.dumps(dag)
        return self._unions[closure]

    def view(self):
        """The composed view: the packs shown, with your store merged in."""
        if self._view is None:
            from ontodag import OntoDAG, native
            view = native.loads(self._union()) if self._closure() else OntoDAG()
            view.merge(self.mine.dag)
            self._view = view
        return self._view

    # -- reading ---------------------------------------------------------- #

    def _prelude_names(self):
        return {name for name, places in self.vocab.places.items()
                if any(p == "prelude" for p, _ in places)}

    def _names(self):
        """Your store's own names: no root, no values, nothing the prelude
        declares."""
        hidden = self._prelude_names()
        return [n for n in self.mine.dag.nodes
                if n != "*" and "(" not in n and n not in hidden]

    def _source(self, child, parent):
        """Whose edge `child ⊑ parent` is: "mine", or the first pack shown
        that has it."""
        mine = self.mine.dag.nodes.get(child)
        if mine is not None and any(p.name == parent for p in mine.parents):
            return "mine"
        read = self._closure()
        for pack, parents in self.vocab.places.get(child, ()):
            if pack in read and parent in parents:
                return pack
        return "view"

    def tree(self):
        """Your categories for the side list: each top one, and below it
        those of yours with something of yours below them, as
        [name, depth, how many of yours are below]."""
        dag = self.mine.dag
        names = set(self._names())
        kids = {}
        for n in names:
            for p in dag.nodes[n].parents:
                if p.name in names:
                    kids.setdefault(p.name, []).append(n)
        tops = sorted(n for n in names if not any(p.name in names for p in dag.nodes[n].parents))
        out = []
        stack = [(t, 0, (t,)) for t in reversed(tops)]
        while stack:
            name, depth, path = stack.pop()
            out.append([name, depth, dag.nodes[name].descendant_count])
            for k in sorted(kids.get(name, ()), reverse=True):
                if k not in path and kids.get(k):
                    stack.append((k, depth + 1, path + (k,)))
        return self._answer(tree=out, count=len(names))

    def node(self, name):
        """A category in the view: what is above and below it and whose
        each edge is, where the vocabularies place it, and what is filed
        under `about(name)`."""
        view = self.view()
        n = view.nodes.get(name)
        places = [[pack, list(parents)] for pack, parents in self.vocab.places.get(name, ())]
        if n is None:
            return self._answer(name=name, found=False, places=places, shown=self._closure())
        root = view.root.name
        above = sorted([p.name, self._source(name, p.name)] for p in n.parents if p.name != root)
        children = sorted(n.neighbors, key=lambda c: (self._source(c.name, name) != "mine", c.name))
        shown = children[:self.limit]
        below = [[c.name, c.descendant_count, self._source(c.name, name)] for c in shown]
        about = []
        a = view.nodes.get(f"about({name})")
        if a is not None:
            for c in sorted(a.neighbors, key=lambda c: c.name):
                about.append([c.name, sorted(p.name for p in c.parents
                                             if p is not a and p.name != root)])
        return self._answer(name=name, found=True, mine=name in self.mine.dag.nodes,
                            places=places, shown=self._closure(), count=n.descendant_count,
                            above=above, below=below, more=len(children) - len(shown),
                            about=about)

    def get(self, query):
        """Everything below all the terms, in the view; yours first."""
        import shlex
        try:
            terms = shlex.split(query)
            answer = sorted(item.name for item in self.view().get(terms))
        except ValueError as e:
            return self._answer(query=query, error=str(e))
        mine = set(self._names())
        yours = [n for n in answer if n in mine]
        others = [n for n in answer if n not in mine]
        return self._answer(query=query, count=len(answer), mine=yours[:self.limit],
                            others=others[:self.limit], more=max(0, len(others) - self.limit))

    def suggest(self, text, limit=8):
        from ontodag.suggest import suggest
        return self._answer(text=text, suggestions=suggest(
            text, self.vocab, mine=self._names(), shown=self._closure(), limit=limit))

    # -- writing ---------------------------------------------------------- #

    @staticmethod
    def _spelled(text):
        """A name as the person typed it, spelled as names are: a phone
        number with its spaces and dashes taken out, a typed term as typed,
        anything else lowercase with dashes for spaces."""
        import re
        t = text.strip()
        if re.fullmatch(r"\+[\d\s().-]+", t):
            return re.sub(r"[\s().-]", "", t)
        if "(" in t:
            return t
        return "-".join(t.lower().split())

    def add(self, item, under=""):
        """Put `item` into your store under the categories named in
        `under`. A category not yet in your store is put at its top first,
        as a name only, whether a vocabulary has it or the person made it
        up (both are said in the answer); a typed value brings the
        prelude's declarations if your store lacks them."""
        import json
        import shlex
        try:
            parents = [self._spelled(p) for p in shlex.split(under)]
        except ValueError as e:
            return self._answer(error=str(e))
        item = self._spelled(item)
        if not item:
            return self._answer(error="name what to add")
        dag = self.mine.dag
        prelude = 0
        if any("(" in p for p in parents + [item]) and "dimension" not in dag.nodes:
            prelude = json.loads(self.mine.prelude())["added"]
        created, taken = [], []
        for p in dict.fromkeys(parents):
            if "(" not in p and p not in dag.nodes and p != item:
                (taken if p in self.vocab.places else created).append(p)
        for p in taken + created:
            answer = json.loads(self.mine.put(p, ""))
            if "error" in answer:
                return self._answer(error=answer["error"])
        answer = json.loads(self.mine.put(item, " ".join(shlex.quote(p) for p in parents)))
        if "error" in answer:
            self._view = None
            return self._answer(error=answer["error"], created=created, taken=taken)
        self._mirror([(p, []) for p in taken + created] + [(answer["put"], answer["under"])])
        return self._answer(put=answer["put"], under=answer["under"], taken=taken,
                            created=created, prelude=prelude, changed=True,
                            count=len(self._names()))

    def _mirror(self, puts):
        """The same puts into the view, if it is built; rebuilt instead
        where one is refused there (merge never refuses)."""
        if self._view is None:
            return
        try:
            for item, parents in puts:
                if item in self._view.nodes and not parents:
                    continue
                self._view.put(item, parents)
        except ValueError:
            self._view = None

    def remove(self, names):
        answer = self.mine.remove(names)
        self._view = None
        return answer

    # -- your files (BROWSER.md §17, questions 40 to 46) ------------------- #
    #
    # The page lists a folder (or single files) and hashes what it reads;
    # `ontodag.folders` does the rest, as for `odag folder` and `odag file`.
    # The folder is read, never written, and its kinds are a layer that is
    # never stored.

    def files_plan(self, listing):
        """Which of a folder's files to read: `listing` is JSON [[path, size,
        mtime], ...]; hidden folders, caches and temporary files are not
        read. `media`: those read that are photos or videos, whose own
        metadata the page reads too (`capture_of`)."""
        import json
        from ontodag import folders
        rows = json.loads(listing)
        read = [i for i, row in enumerate(rows) if not folders.skipped(row[0])]
        media = [i for i in read if folders.is_media(rows[i][0])]
        return self._answer(read=read, media=media, skipped=len(rows) - len(read))

    def files_look(self, seen, name="", whole=True):
        """Look at the files the page read: `seen` is JSON [{path, size,
        mtime, sha256, taken}], sha256 null for a file too large to read in
        the page, taken ({time, geo}, from `capture_of`) for a photo or a
        video. With `whole` they are a folder's files: a content that is a
        new version of a filed document is attached and said (to undo), as
        `odag folder` does, unless it was undone this session. Single files
        cannot tell that an old version is gone, so a document of their
        name is offered instead (`like`). Answers what the files are by
        kind, how many contents are filed, and the work list: the contents
        not yet filed, copies as one."""
        import json
        from ontodag import folders
        from ontodag.capture import Capture
        found = [folders.Seen(s["path"], int(s["size"]), float(s["mtime"]), s.get("sha256"),
                              Capture(**s["taken"]) if s.get("taken") else None)
                 for s in json.loads(seen)]
        self.folder = folders.Folder(found)
        dag = self.mine.dag
        attached, ambiguous = [], []
        if whole:
            edits, unsure = folders.recognise_edits(dag, self.folder)
            had_heads = all(h in dag.nodes for h, _parents in folders.HEADS)
            puts = []
            for s, doc in edits:
                version = folders.version_name(s.sha256)
                if (version, doc) in self._declined:
                    continue
                puts.append((version, folders.attach(dag, s, doc)))
                self.mine.changed = True
                attached.append({"path": s.path, "document": doc, "version": version})
            if had_heads:
                self._mirror(puts)
            elif puts:
                self._view = None
            ambiguous = [{"sha256": s.sha256, "path": s.path, "documents": docs} for s, docs in unsure]
        kinds = {}
        for s in found:
            kind = folders.kind_of(s.path) or "other"
            kinds[kind] = kinds.get(kind, 0) + 1
        filed = sum(1 for h in self.folder.by_hash if folders.version_name(h) in dag.nodes)
        work = []
        for h, files in folders.unfiled(dag, self.folder).items():
            first = files[0]
            work.append({"sha256": h, "paths": [f.path for f in files], "name": first.name,
                         "folder": first.folder, "kind": folders.kind_of(first.path) or "other",
                         "size": first.size, "mtime": first.mtime,
                         "like": folders.named_like(dag, first)})
        work.sort(key=lambda w: (w["kind"], w["paths"][0]))
        return self._answer(name=name, files=len(found), kinds=dict(sorted(kinds.items())),
                            unhashed=len(self.folder.unhashed), filed=filed, attached=attached,
                            ambiguous=ambiguous, unfiled=work, changed=self.mine.changed,
                            count=len(self._names()))

    def files_file(self, shas, under="", versions="{}"):
        """File contents from the last look (JSON list of SHA-256s) under
        the categories named in `under`: each as a document named by its
        file, with the content as a version, or as a new version of the
        document `versions` names for it (JSON {sha256: document}). A
        category not yet in your store is put at its top first, as a name
        only (question 39)."""
        import json
        import shlex
        from ontodag import folders
        try:
            parents = [self._spelled(p) for p in shlex.split(under)]
        except ValueError as e:
            return self._answer(error=str(e))
        version_of = json.loads(versions)
        folder = self.folder
        chosen = json.loads(shas)
        missing = [h for h in chosen if folder is None or h not in folder.by_hash]
        if missing:
            return self._answer(error=f"{len(missing)} of these were not in the files looked at; look again")
        dag = self.mine.dag
        taken, created = [], []
        for p in dict.fromkeys(parents):
            if "(" not in p and p not in dag.nodes:
                (taken if p in self.vocab.places else created).append(p)
        filed, puts, prelude = [], [(p, []) for p in taken + created], 0
        for h in chosen:
            s = folder.by_hash[h][0]
            try:
                done = folders.file(dag, s, parents, version_of=version_of.get(h))
            except ValueError as e:
                self._view = None
                return self._answer(error=str(e), filed=filed)
            self.mine.changed = True
            prelude += done["prelude"]
            if parents or done["made"]:
                puts.append((done["document"], parents))
            if done["parents"]:
                puts.append((done["version"], done["parents"]))
            filed.append({"path": s.path, "document": done["document"], "version": done["version"],
                          "made": done["made"]})
        if prelude:
            self._view = None
        else:
            self._mirror(puts)
        return self._answer(filed=filed, under=parents, taken=taken, created=created,
                            prelude=prelude, changed=True, count=len(self._names()))

    def files_undo(self, versions):
        """Take back versions a look attached (JSON list): they are removed,
        and not attached again this session; they wait in the work list,
        with their document offered."""
        import json
        import shlex
        from ontodag import folders
        names = json.loads(versions)
        dag = self.mine.dag
        for v in names:
            doc = folders.document_of(dag, v)
            if doc:
                self._declined.add((v, doc))
        answer = json.loads(self.mine.remove(" ".join(shlex.quote(v) for v in names)))
        self._view = None
        if "error" in answer:
            return self._answer(error=answer["error"])
        return self._answer(undone=names, changed=answer["changed"], count=len(self._names()))
