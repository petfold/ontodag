# OntoDAG in a browser, against Swarm

**Status: adapters written and unit-tested; nothing has run in a browser.**
Everything below is either a measurement (marked as such) or a design
awaiting a first run. Two questions for Peter are open in §7 and they change
what §4 should target, so read those before building the page.

Written 2026-08-02, after making the base install pure-Python — which is
what turned this from impossible into a page you can open.

---

## 1. Why this is possible now, and was not yesterday

`pip install ontodag` used to require `owlready2`, which ships **sdist-only**
with a Cython extension. `micropip` cannot build sdists, so
`micropip.install("ontodag")` failed outright. One line in `pyproject.toml`
blocked the entire in-browser story while B1 cheerfully reported the core was
dependency-free — the boundary was asserted in code and not in metadata.

Measured after the change:

| | |
|---|---|
| `ontodag` wheel | `py3-none-any` |
| `recordstore` on PyPI | publishes `py3-none-any.whl` (not only an sdist) |
| base install | 2 packages, 896 KB, no compiled code anywhere |
| stdlib the core imports | `calendar datetime decimal enum fractions locale math numbers re contextlib` — all present in Pyodide |

So the whole base closure is micropip-installable. This is now guarded by
`TestTheBoundaryIsAlsoDeclared` in `tests/test_boundaries.py`, which fails if
a hard dependency or a compiled extension creeps back in.

**`ontodag[swarm]` is permanently out of reach in the browser** and always
will be: it pulls 25 further packages including `coincurve` and
`pycryptodome`, compiled secp256k1 and crypto. No amount of effort makes
that run under Pyodide. The browser therefore reaches Swarm *through
JavaScript*, never through the Python Swarm stack. That is a structural
fact, not a temporary gap, and it is the reason `ontodag.browser` exists.

## 2. What already exists

`src/ontodag/browser.py`, with `tests/test_browser.py` (9 tests, fake
JavaScript):

| class | role |
|---|---|
| `JsBytesStore` | `recordstore` BytesStore over a JS object with async `upload`/`download` |
| `JsFeedPointer` | Pointer over a Swarm feed with async `read`/`write` |
| `LocalStorageBytesStore` | synchronous, content-addressed, over `window.localStorage` — the browser's `rs:PATH` |

The seams are tiny, which is the whole reason this is tractable:

```python
BytesStore:  put(bytes) -> ref      get(ref) -> bytes
Pointer:     get() -> ref | None    set(ref) -> None
```

Everything above them — the trie, canonical roots, snapshots, proofs, all of
OntoDAG — is pure Python with no filesystem and no sockets.

The test that matters most already passes:
`test_the_root_is_the_same_one_a_laptop_would_compute` — a JS-backed store
produces the byte-identical canonical root to an on-disk one. That is what
makes a browser a **peer** rather than a silo: it can publish something a
laptop will recognise, and verify something a laptop published.

The adapters are deliberately **not bee-js specific**. They talk to a
duck-typed JS object, so bee-js, a `fetch` wrapper, a gateway, or an in-page
node all work unchanged. The Swarm side of the browser story is moving; the
adapter should not have to move with it.

## 3. The one real obstacle

`BytesStore.get/put` are synchronous. Every browser network API is
asynchronous. Python cannot block on a JS promise from the main thread —
the event loop that would resolve it is the one being blocked. **This is the
platform, not a Pyodide quirk.**

Three ways out:

| | works | costs |
|---|---|---|
| **JSPI** — `pyodide.ffi.run_sync` | recent Chromium | narrow support matrix; check current Pyodide docs before relying on it |
| **Worker + `Atomics.wait`** | broadly | needs COOP/COEP headers on the page; awkward for a local file |
| **Move the boundary to load/save** | everywhere, today | fetches the whole store rather than walking it lazily |

`JsBytesStore` takes the bridge as a constructor argument precisely so this
choice belongs to the deployment rather than to the library.

## 4. Recommended first milestone: async at load/save only

`EagerOntoDAG` already hydrates the whole store on construction and commits
in a batch, so the network is touched at exactly two moments — both of which
JavaScript can `await` before handing control to Python:

```
open :  await node.download(root)  ->  seed a MemoryBytesStore
        (or LocalStorageBytesStore, so a reload needs no network)
work :  put / get / below / certificates — pure Python, no network
save :  dag.commit() -> canonical root -> await node.upload(new blobs)
```

Between load and save it is an ordinary in-memory DAG with real canonical
roots. Blobs are content-addressed, so a save pushes only what is new and
re-uploading is idempotent.

Sketch:

```html
<script src="https://cdn.jsdelivr.net/pyodide/vX.Y.Z/full/pyodide.js"></script>
<script type="module">
  const pyodide = await loadPyodide();
  await pyodide.loadPackage("micropip");
  await pyodide.runPythonAsync(`
      import micropip
      await micropip.install("ontodag")     # brings recordstore
  `);
  pyodide.globals.set("swarm", myBrowserBeeNode);
</script>
```

**Trade-off, stated plainly:** the whole store is fetched. Fine to a few
thousand nodes. Beyond that the answer is milestone two, not a bigger
download.

## 5. Second milestone: the lazy thin client

`LazyOntoDAG` fetching records as a query walks is the real prize — it is
what makes a browser able to query a large published ontology without
downloading it, and the cone-summary index (`ontodag.cones`) already exists
to keep broad queries cheap. Measured on a 447-record fixture: a two-broad-
term query drops from 375 record fetches to 3 records + 3 index fetches.

This one **does** need a synchronous bridge (JSPI or worker), because the
fetches happen mid-traversal and there is no batch boundary to hoist them
to. Do it after milestone one proves the plumbing.

## 6. Feeds and signing

The mutable "latest root" is what makes a store followable. Options in the
browser, in preference order:

1. **The node signs** — if the in-browser node exposes feed writing, use
   `JsFeedPointer` and the store is followable by anyone.
2. **JS-side signing** — bee-js or a wallet extension signs; same adapter.
3. **localStorage** — a private root, not publishable. Fine for a first
   demo; state it as a limitation rather than shipping it silently.

Python-side signing is **not an option** (see §1).

## 7. Open questions — answer before writing the page

1. **What does the in-browser node expose to page JavaScript?** A bee-js
   style object with `upload`/`download`, a local HTTP endpoint the page can
   `fetch`, or something else? This decides whether `JsBytesStore` is used
   as-is or wants a thin `fetch` wrapper.
2. **Can it sign feeds in-browser?** Decides §6, and therefore whether the
   first demo can publish a followable root or only a private one.

## 8. What a first page should demonstrate

Ordered by how much each proves:

1. `micropip.install("ontodag")` succeeds — proves §1 end to end.
2. Build a small DAG, query it, run `below` on a typed value — proves the
   core is intact under wasm, including the dimension arithmetic.
3. Print the canonical root, and check it equals the one the same
   knowledge produces on a laptop — proves peerhood (§2).
4. Save to the node, reload the page, restore from the root alone — proves
   the round trip.
5. Produce an `is_below` certificate in the browser and verify it against
   the root — proves the browser can make claims a stranger can check.

Step 3 is the one worth doing first: if the roots disagree, something about
the encoding differs under wasm and everything else is built on sand.

## 9. Known unknowns

- Nothing here has run in Pyodide. The failure most likely to bite first is
  not the design but something dull: a Pyodide version pin, a CORS header on
  the PyPI fetch, `micropip` resolving a version we did not expect.
- Wheel freshness: `micropip.install("ontodag")` takes the latest PyPI
  release. **0.10.1 on PyPI still has the old hard dependencies** and will
  therefore fail — the pure-Python base install is unreleased as of writing.
  Until it ships, a demo must install from a locally-served wheel.
- Pyodide's own size (~10 MB, cached after first load) dominates the
  transfer; ontodag's 896 KB is noise beside it.
