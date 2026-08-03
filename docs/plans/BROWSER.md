# OntoDAG in a browser, against Swarm

**Status: adapters written and unit-tested, cost measured, nothing has run
in a browser.** Everything below is either a measurement (marked as such, and
reproducible with `experiments/browser_rounds.py`) or a design awaiting a
first run. Two questions for Peter are open in §7.

Written 2026-08-02, after making the base install pure-Python — which is
what turned this from impossible into a page you can open.

**The short version.** A shared ontology on Swarm is too large to download,
so the browser fetches only the fragment each query touches. Measured on a
3,221-node store, a session costs **~12 sequential round trips for the first
query and 4–5 for each one after** — roughly 250 ms per query at 50 ms
latency, against a store that was never downloaded. Three things get it
there: the cone index (mandatory, not an optimisation), frontier batching
(the one real code change needed — `lazy.py` has the seam and does not use
it), and miss-and-replay (which removes any need for JSPI).

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

Four ways out. §5 explains why the last one wins:

| | works | costs |
|---|---|---|
| **JSPI** — `pyodide.ffi.run_sync` | recent Chromium | narrow support matrix; check current Pyodide docs before relying on it |
| **Worker + `Atomics.wait`** | broadly | needs COOP/COEP headers on the page; awkward for a local file |
| ~~**Load/save boundary**~~ | — | **rejected**: it downloads the whole store, and the shared ontology is far too large for that. Survives only as a cache for a user's own small DAG |
| **Miss-and-replay** | everywhere, today | a few free in-memory replays; needs the store to raise instead of block |

`JsBytesStore` takes the bridge as a constructor argument precisely so this
choice belongs to the deployment rather than to the library.

## 4. The requirement is lazy, and it is measured

A shared ontology on Swarm can be far too large to download, so the browser
must fetch **only the fragment a query touches**. That rules out
whole-store load as the first milestone; it survives only as a cache for a
user's *own* small DAG, never for the shared one.

The number that decides feasibility is not fetches but **sequential round
trips**: fetches issued together cost one, only dependencies cost more.
Measured by `experiments/browser_rounds.py` on a 3,221-node store —

| query | plain | + cone index | + batching | both |
|---|---|---|---|---|
| one specific term | 47 | 51 | **8** | 12 |
| two mid terms | 65 | 69 | **13** | 17 |
| one broad term | 305 | **10** | 14 | 10 |
| two broad terms | 366 | **14** | 19 | 14 |

and the number that actually matters, a session sharing one cache (both
features on), because blobs are immutable so nothing is ever re-fetched:

| query | rounds | cache after |
|---|---|---|
| 1 — `mid5` | 12 | 51 blobs |
| 2 — `top0` | 5 | 56 |
| 3 — `mid5, mid12` | 5 | 74 |
| 4 — `top0, top1` | 4 | 78 |
| 5 — `mid7` | 5 | 108 |
| 6 — `top3` | 4 | 112 |

**First query ~12 round trips, every one after 4–5.** At 50 ms that is
0.6 s then ~250 ms — an interactive experience against a store you never
downloaded. Six queries cost 112 blobs.

Three things make that work, and all three are needed:

**(a) The cone index is mandatory, not an optimisation.** Broad queries go
from 305/366 rounds to 10/14, because a published summary answers the query
instead of walking the cone — 622 records become 2. Any browser deployment
must publish `odag index` alongside the data.

**(b) Frontier batching, which `lazy.py` does not do yet.** `_expand_many`
exists as the seam and *nothing calls it*: the traversals in
`get_descendants`/`get_ancestors` pop one node at a time, so each node costs
a round trip. Expanding a whole frontier per level takes specific queries
from 47 to 8 rounds. `experiments/browser_rounds.py` contains
`BatchedLazy`, a level-order subclass, which is the shape the change should
take. This is the one real code change the browser path needs.

Note the two are complementary rather than additive, and the index is not
free: on a *cold* cache it costs a few rounds of manifest that a specific
query never recoups (8 → 12). In a session that overhead is paid once, which
is why the session table is the honest one.

**(c) Miss-and-replay, which removes the need for JSPI entirely.**

## 5. Bridging sync and async without JSPI

Blobs are immutable and content-addressed, so a query can be *replayed for
free* — in-memory work over data that cannot change underneath it:

```
cache = {}
while True:
    try:    answer = dag.get(terms)      # pure sync, over the cache
    except Missing as m:
        await node.download(m.refs)      # one round trip, many refs
        continue                          # replay: free
```

No JSPI, no worker, no COOP/COEP headers, no fork of the query planner. The
store raises instead of blocking; the loop supplies what was missing and
tries again. The measurements above are exactly this scheme.

JSPI (`pyodide.ffi.run_sync`) remains a *nice-to-have*: it removes the
replay, so the same query costs the same round trips with less CPU. It is
no longer a prerequisite, which matters because its support matrix is
narrow.

What the store must provide, beyond `ontodag.browser.JsBytesStore`:

- a cache-or-raise `get`, carrying the wanted refs on the exception;
- collection of misses across a frontier, so a level is one round trip
  (needs (b) above to be worth anything);
- `download_many` on the JS side, so a round trip is one request.

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
4. Query a **large published store lazily** — the point of the exercise.
   Confirm the round-trip count matches §4 in the real world; latency and
   HTTP overhead will make it worse than the simulation, and by how much is
   the number nobody has yet.
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
- The round-trip counts in §4 are a *simulation* on an in-memory store: they
  count dependencies exactly but model no latency, no HTTP overhead, no
  connection limits, and no Swarm retrieval variance. A real node fetching
  from the network will be worse, and the interesting question is whether
  it is worse by a constant or by a lot.
- Frontier batching (§4b) is measured via a subclass in the experiment, not
  implemented in `lazy.py`. Landing it there needs the traversals to go
  level-order, and `_expand_many` to become a real batched store call —
  `recordstore` has `get_many`, so the plumbing exists on both sides.
