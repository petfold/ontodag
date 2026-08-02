"""Running OntoDAG in a browser, against Swarm.

**Status: written, not yet run in a browser.** The logic below is covered by
tests using a fake bridge, and the packaging constraints it depends on are
checked in `tests/test_boundaries.py`, but nobody has loaded this into
Pyodide against a live Bee node. Treat it as a design that compiles, not as
a verified path.

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

## Deliberately not bee-js specific

The store talks to a small duck-typed JS object with `upload` and `download`,
so it works with bee-js, a `fetch` wrapper against a Bee HTTP endpoint, a
gateway, or an in-page node if one exists. The Swarm side of the browser
story is moving; the adapter should not have to move with it.
"""


class JsBytesStore:
    """A `recordstore` BytesStore backed by a JavaScript object.

    `js_store` must provide:

        upload(data: Uint8Array) -> Promise<string>   # returns the reference
        download(ref: string)    -> Promise<Uint8Array>

    `bridge` turns a returned promise into a value synchronously; see the
    module docstring for what can implement it.

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
        return self._to_bytes(self._bridge(self._js.download(str(ref))))

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
