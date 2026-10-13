# OntoDAG in a browser, against Swarm

**Status (2026-09-02): the offline half HAS RUN under wasm.** §8 steps
1–3 are done and repeatable: `demo/pyodide/check.py` installs the released
`ontodag` wheel from PyPI into Pyodide 0.27.7 (under node), builds the
London→Rome knowledge, answers a typed query and a `below`, and commits —
**the canonical root is byte-identical to the native one**
(`be7afb84…`; install 5 s, run 0.3 s). The `odag` interpreter itself runs
there too (`dispatch` over an `rs:` store on Pyodide's in-memory
filesystem, with `history`/`undo` working, and prelude v3 hydrating to its
golden root `9a732928…`). `demo/pyodide/index.html` is the page: a console
running that interpreter, no server, no build step. What has NOT run is the
Swarm half — §4–§6 below remain a measured design; the two questions for
Peter in §7 still gate it. Everything else below is either a measurement
(marked as such, and reproducible with `experiments/browser_rounds.py`) or
a design awaiting a first run.

Written 2026-08-02, after making the base install pure-Python — which is
what turned this from impossible into a page you can open.

**2026-09-25: the key plan runs here too** (SHARING_ON_SWARM.md §13).
`demo/pyodide/keyplan.mjs` installs a local wheel and runs
`keyplan_check.py`. Pyodide 0.27.7 ships pycryptodome but not coincurve,
so `ontodag.act` falls back to its pure-Python secp256k1. The script
publishes a store's shares, reads them as two readers (both exact, and the
timeline equals the server's), revokes lazily, and checks that the revoked
reader can't open the next post. That takes 0.5 s after a 7 s install.
Reading a friend's shares in a browser therefore needs no TypeScript port of
the crypto; the Swarm half, as above, still hasn't run.

**2026-10-11: the Swarm half has its clients, and identity is decided.**
§7's two questions are answered for Freedom Browser (§7), and the other
in-browser clients are surveyed (§10). The adapter moves down from whole
blobs to four calls on chunks (§10.1), so every client gives the same roots
as a laptop. Identity is decided: one key derived from one wallet
signature, used in every client (§11, Peter's option A). ontodag keeps its
own access control rather than the node's ACT (§12). Two requests are
filed with Freedom: #647 (publish a single-owner chunk the page signed) and
#648 (open ACT shares made to the user's node).

**2026-10-12: the read-only page runs in Freedom Browser** (§13).
`demo/freedom/` reads a published pack from Swarm through Freedom's
`window.swarm`, with every answer equal to Python reading the same root
natively. JSPI carries it, not miss-and-replay: Chromium has shipped JSPI
on by default since version 137, and Freedom is Electron 44, so Python's
synchronous store calls simply wait on the page's Swarm reads (§3, §5).
loopmarket's read-only market page runs on the same layer (its
BROWSER.md §5a).

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

The mutable "latest root" is what makes a store followable. A store's feed
is a standard Bee sequence feed: the topic is keccak256 of the name, an
update is a single-owner chunk at keccak256(identifier ‖ owner) with the
identifier keccak256(topic ‖ 8-byte big-endian index), and the payload is
the writer's timestamp and the root (`recordstore`'s `SwarmFeedPointer` and
its feed-update format). Anything that can write a signed chunk can
therefore continue a feed a laptop started, and the other way round.

Who signs, in the browser (answered 2026-10-11):

- **The key that owns the feed is the user's key from §11**, derived from
  one wallet signature and held by the page. Signing in the page works
  with a JavaScript library or with the pure-Python secp256k1 that
  `ontodag.act` already falls back to under Pyodide. The objection §1
  raised was to the compiled Swarm stack, not to signing itself.
- **Bee signs a single-owner chunk with the Ethereum message prefix** over
  keccak256(identifier ‖ chunk address) (`bee/pkg/crypto/signer.go:84-91`,
  `pkg/soc/soc.go:128-134`), exactly what a wallet's `personal_sign`
  produces. So a wallet could sign a feed update too, at one approval per
  update; under §11 it doesn't have to.
- **Freedom signs only with its own identities today** (§10): a page can
  write our feed format through `swarm_writeSingleOwnerChunk` with our
  identifier, but the owner is then a Freedom identity, not the user's key.
  Publishing a chunk the page signed is request #647.
- **localStorage** stays what it was: a private root, not publishable.

## 7. Open questions — answered for Freedom (2026-10-11)

1. **What does the in-browser node expose to page JavaScript?** In
   Freedom, a permissioned `window.swarm` provider, and nothing else: a
   page's requests to the node's HTTP API are blocked. It reads chunks,
   signed chunks and feed entries without permission, publishes one chunk
   at a time paid from the node's postage, and writes signed chunks as one
   of Freedom's identities (§10). `JsBytesStore` and `JsFeedPointer`
   therefore get an adapter over these calls, in the four-call shape of
   §10.1. Other clients answer differently (§10), which is why the seam is
   that narrow.
2. **Can it sign feeds in-browser?** Yes, but only as a Freedom identity
   (§6). With the user's own key (§11), a Freedom page can follow feeds
   today and continue them once #647 is accepted. Until then a Freedom page
   is read-only for the user's own stores.

## 8. What a first page should demonstrate

Ordered by how much each proves (1–3 **done 2026-09-02**, see the status
note at the top; 4–5 wait on the Swarm half):

1. ~~`micropip.install("ontodag")` succeeds~~ — proves §1 end to end.
   Done: 0.18.1 from PyPI, 5 s under node, no local wheel.
2. ~~Build a small DAG, query it, run `below` on a typed value~~ — proves
   the core is intact under wasm, including the dimension arithmetic.
   Done: `get transport duration(..10h)` and `below BA2551 duration(..3h)`
   answer identically.
3. ~~Print the canonical root, and check it equals the one the same
   knowledge produces on a laptop~~ — proves peerhood (§2). Done:
   `demo/pyodide/check.py` exits 0 iff the two roots agree; they do.
4. Query a **large published store lazily** — the point of the exercise.
   Confirm the round-trip count matches §4 in the real world; latency and
   HTTP overhead will make it worse than the simulation, and by how much is
   the number nobody has yet.
5. Produce an `is_below` certificate in the browser and verify it against
   the root — proves the browser can make claims a stranger can check.

Step 3 is the one worth doing first: if the roots disagree, something about
the encoding differs under wasm and everything else is built on sand.

The Swarm half, in order (2026-10-11):

1. **Read-only, in Freedom:** step 4 against the published core pack, over
   `swarm_readChunk` and `swarm_readFeedEntry`, giving the real round-trip
   counts that §4 only simulates. This needs no key, no postage and no
   request upstream. loopmarket's first page is the same kind of thing:
   its own BROWSER.md.
2. **The same page over a public gateway**, read-only, through the same
   four calls (§10.1).
3. **Writing the user's own store** under the §11 key: Weeb-3 or an HTTP
   node today, Freedom once #647 lands.
4. Step 5, certificates, then sharing (`keyplan` as reader and author).

## 9. Known unknowns

- ~~Nothing here has run in Pyodide.~~ The offline half has (node harness
  and the page); none of the dull failures predicted here occurred. The
  Swarm half still has not.
- ~~Wheel freshness~~ — resolved: every release since 0.11 is pure Python
  on PyPI, and `micropip.install("ontodag")` resolves it directly (verified
  with 0.18.1). `check.mjs VERSION` pins a release when comparing one.
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

## 10. The in-browser Swarm clients (surveyed 2026-10-11)

Peter asked for one solution that works with any in-browser Swarm client,
adapting to Freedom where it does things its own way. What each client
lets a page do, read from their source on 2026-10-11 (external projects
move fast; check again before relying on a line):

| | Freedom Browser | Weeb-3 | Bee or Ant over HTTP | public gateway |
|---|---|---|---|---|
| what the page needs | nothing: the browser injects `window.swarm` | a wasm library, a SharedWorker and a service worker, over HTTPS | a node that allows the page's origin (CORS) | nothing |
| read a chunk | yes, no permission; Freedom checks the address | yes; a signed chunk comes back without its signature; failures come back as empty results | yes | yes |
| write a chunk | yes, one at a time (≤4096 bytes), paid from the node's batch | yes, with a stamp the caller makes | yes, from the node's batch or with a stamp the caller makes | no |
| write a signed chunk | yes, any identifier, but always signed by a Freedom identity (per-site key, node key or Freedom's wallet) | yes, a chunk the caller signed | yes, a chunk the caller signed (`POST /soc/{owner}/{id}?sig=`) | no |
| ACT | the node (Ant v0.5.64) has it; pages can't use it | planned | yes, with the node's key | no |
| status | released browser | experimental, one author, no releases | stable | stable |

Sources:

- **Freedom** (solardev-xyz/freedom-browser at fb540328):
  - the provider is `src/main/swarm/swarm-provider-ipc.js` (spec 1.0, documented only in source; their #179);
  - the chunk calls are in `chunk-service.js` (reads checked against the requested address, `:128-159`);
  - the node's HTTP API is blocked to pages, and `bzz://` forwards only allowlisted headers, dropping `Swarm-Act*` (`bzz-protocol.js:88-105`, their #429).
- **Ant** (freedom-hq/ant v0.5.64, the version Freedom pins):
  - ACT matches Bee's, always with the node's key (`crates/ant-gateway/src/act.rs:31-33`, their PR #30);
  - it accepts caller-signed chunks and caller-made stamps over HTTP;
  - there is no WebAssembly build and no browser transport, so Ant runs only as `antd` or embedded through `ant-ffi`.
- **Weeb-3** (lat-murmeldjur/weeb-3 at 728ff33):
  - a Rust node compiled to WebAssembly that reaches Bee peers over secure WebSockets;
  - `postPushChunk(data, soc, address, stamp)` takes a chunk and stamp the caller built (`src/library.rs:778-799`);
  - its own uploads are stamped by a vault on another origin;
  - its feeds wrap a manifest;
  - ACT is listed as planned (README:307), and the README calls the project experimental.
- **dappdata** (petfold/dappdata) recorded Weeb-3 as retrieval-only at first, then claiming uploads (`spikes/s3/RESULTS.md`), and showed that a Bee node with CORS set accepts chunks a page stamped itself.

### 10.1 The seam: four calls

Every client reads chunks, and all but a gateway write chunks and signed
chunks. So the adapter is four calls:

- read a chunk;
- read a signed chunk;
- write a chunk;
- write a signed chunk.

Two shortcuts are optional: a feed's latest entry (Freedom's
`swarm_readFeedEntry`, Bee's `/feeds`) and reading a whole blob in one call
(Weeb-3's `retrieveBytes`, Bee's `/bytes`).

Everything above the four calls is ours and the same in every client:

- **Chunking and addresses:** splitting blobs into chunks and computing
  their addresses (recordstore's Swarm addressing), so roots are
  byte-identical to a laptop's.
- **Checking:** verifying every chunk against its address and every
  signature against its owner, so a gateway or an experimental client can't
  hand us wrong data. Weeb-3's signed-chunk reads drop the signature, so
  there we rely on its own check.
- **Feeds** in recordstore's format (§6), written as signed chunks. We use
  neither Freedom's named feeds, whose topic is the origin plus the name
  (`feed-service.js:74-76`), nor Weeb-3's feeds, which wrap a manifest.
- **The rest:** lazy reads with miss-and-replay (§4–§5), and the sharing
  cryptography (§12).

`ontodag.browser`'s `JsBytesStore` and `JsFeedPointer` work at the blob
level today and would move down to these four calls. Who pays and who
signs is each adapter's business:

- **Freedom:** the client holds the keys and the postage.
- **Weeb-3 and HTTP nodes:** the page brings them, a stamper for a batch the
  user owns (dappdata's client-side stamper) and the user's key from §11.

Whether the adapters live in dappdata, whose `Transport` interface is
already this idea in TypeScript, or in a thin layer of our own, is open.

### 10.2 Where Freedom stays different

- No access to the node except through `window.swarm`, with a permission
  prompt per site. The node pays for every chunk.
- Freedom's keys never leave it: there is no ECDH call, and no call takes a
  chunk the page signed (#647).
- Identities, permissions and stored data belong to the page's origin. A
  page under a `bzz://` hash gets a new origin with every version, so it
  should be served under a stable ENS name.
- No ACT for pages (§12, #648), and nothing at all in private windows.
- One chunk of at most 4096 bytes per call, and at most 10 MB per upload.

### 10.3 What no page can do

- **Work after it is closed:** there is no background process.
- **Run the compiled Swarm extras:** the Python Swarm stack and coincurve
  don't run there (§1).
- **Graphviz, OWL export, the stdio MCP server or the terminal CLI.**
- **Download a large shared store whole** (§4).

## 11. Identity: one key from one wallet signature (decided A, Peter, 2026-10-11)

**The decision.** The user's identity in the browser is one secp256k1 key,
derived from one wallet signature (dappdata's `entropy.wallet`; a mnemonic
or a passkey also derive it), and the same key in every client. It signs
feed updates, so it owns the user's stores and books. It signs whatever
the protocols sign, loopmarket's offers included, as they are signed now.
It is the sharing key whose ECDH opens what others grant (§12;
SHARING_ON_SWARM.md §2). The page holds it in memory; nothing is stored.

**Why.**

- One identity across Freedom, Weeb-3, HTTP nodes and the command line,
  with no protocol change: loopmarket's raw-hash offer signatures stay as
  they are.
- Sharing works, since the page can do the ECDH.
- No wallet approval per write.

**The alternative, B, not taken:** the wallet itself in every client. It
works in Freedom today, but costs a wallet approval per feed update, needs
loopmarket to accept `personal_sign`-form offer signatures, and still needs
a derived key for sharing, since no wallet does ECDH.

**Consequences.**

- **Freedom** can read the user's stores now and write them once #647 is
  accepted. Until then a Freedom page doesn't write under a Freedom
  identity, because that would be a different person.
- **The key lives in page memory**, so the page's code is part of the trust
  base. A `bzz://` page is immutable, but its ENS name can be pointed
  elsewhere by whoever owns it.
- **The address needs a little xDAI** wherever the protocol sends
  transactions (loopmarket's announcements); the wallet funds it with one
  transaction.
- **The command line has the same identity** only if it derives or imports
  that key; how is open.

**For now: the key is a file (questions 37 and 38, decided 2026-10-13, §14.3).**
Until the identity is settled, the page writes as `odag` and `loop` do: with
a random key kept in a file, and the node's batches. Derivation from a wallet
signature comes later as the way that same key is carried to a new device,
so nothing changes owner.

**Still open:**

- the rest of S1 (SHARING_ON_SWARM.md §11): which message the wallet signs,
  meaning a reserved protocol identity that a phishing site can also ask
  for, as dappdata T14 accepts, and personas and devices;
- dappdata as the shared layer (§10.1);
- which clients come first (§8 orders Freedom read-only first).

## 12. Access control and the node's ACT (2026-10-11)

ontodag keeps its own access control, `keyplan` over `ontodag.act`'s
primitives, and doesn't use the node's ACT. The two share one building
block: the grantee entry (ECDH lookup and wrap, Bee's stream cipher),
which `ontodag.act` writes byte for byte as Bee does, pinned against
Bee's vectors (`tests/test_act.py`). Beyond it they differ in kind:

- **Categories, not lists.** One grant reaches a whole category cone
  (`act-categories/DESIGN.md` §1).
- **Keys no node holds.** Category keys belong to no node, and readers
  often have no node of their own (a page, an offline store). Bee's and
  Ant's ACT always use the node's key (DESIGN §4; `act.rs:31-33`).
- **The content is sealed,** not only its reference.
- **Every store tier.** It works on every tier and under Pyodide.
- **Canonical tokens.** They are deterministic, so they have a canonical
  root.

Using the node's ACT as well would be a second way to grant access, which
ROLES.md §9 retired.

**One correction to DESIGN's Phase 2.** A caller-supplied access key (a
`Swarm-Act-Access-Key` header) gives a page nothing: holding the access
key, a page decrypts the reference itself and reads the chunks. The header
helps only clients without cryptography, such as curl. What a page can't
do is open a share made to the user's node key; that is Freedom request
#648, filed for the ecosystem rather than for ontodag. SHARING_ON_SWARM.md
S18 stands: grantee entries live in ontodag's store, in Bee's format, so a
Bee-native path stays open.

## 13. The read-only page, built (2026-10-12)

`demo/freedom/` (BROWSER.md §8, step 1 of the Swarm half):

- **`swarm.js`** is the page's whole Swarm layer:
  - **Sources:** `FreedomSwarm` over `window.swarm` and `HttpSwarm` over a
    node or gateway.
  - **`ChunkReader`:** joins chunk trees and checks every chunk against
    its address (vendored noble-hashes keccak). It caps reads in flight,
    waits out a client's read budget, and keeps checked chunks for the
    session and, in IndexedDB, across visits.
  - **`feedRoot`:** a recordstore feed's newest root.
  - **`BlobStore`:** what Python calls.

  `test/` checks it against swarmfs's splitter: addresses, trees from 0 to
  600 KB, tampered and missing chunks, one read per chunk.
- **Python:** `ontodag.browser.open_published(root, js_store)` gives a
  `LazyOntoDAG` with `prefetch=True` over `RecordStore.at(root, ...)`, its
  blobs read through `JsBytesStore` with `run_sync` as the bridge.
  `PageReader` answers the page as JSON. A blob the page could not fetch
  or check is a `BlobUnreachable` (an `OSError`), so a reader fails
  instead of taking a category for absent.
- **recordstore, two changes on its main:**
  - `RecordStore.get_many` reads many records with one batch per trie
    level;
  - an unreachable trie node is `RecordUnavailable`, no longer a
    `KeyError` (it was a fail-open path for every lazy reader).

  The page bundles recordstore's main until a release.
- **`build.py`** assembles one Swarm upload (Pyodide's core, the wheels,
  13.7 MB) and publishes it, its tar deterministic.
- **`check.py`** runs it in Chromium, through a stand-in for Freedom's
  provider and through a node over HTTP.
- **`freedom_check.cjs`** runs it in real Freedom Browser from its
  checkout: a throwaway profile, the Bee node as Freedom's external node,
  `bzz://REF/` through the address bar.

Measured on the core pack (5,030 categories), served by a node that holds
it, with chunks read in parallel:

| | first visit, connected | first visit, not connected | second visit |
|---|---|---|---|
| page ready (Python started, store opened) | 5.1 s | 6.8 s | 4.8 s |
| `fruit` with its 35 children | 1.0 s | 61 s | 0.4 s |
| `food` with its 25 children | 0.6 s | 61 s | 0.2 s |
| `get fruit produce` (63 found) | 0.5 s | 61 s | 0.1 s |
| chunk reads for the session | 376 | 376 | 0 |

- **Not connected:** Freedom lets a site that has not connected read 120
  chunks and 512 KB a minute, so the same 376 reads wait out the budget.
  The page then says so and points to Connect, which gives 600 a minute.
- **Second visit:** the chunks kept in IndexedDB make it free.
- **Record reads:** the session read 107 records in 15 round trips at
  Python's level. Without prefetch, a 258-node cone costs 266 round trips;
  with it, 9.
- **Through the public gateway** (`check.py --gateway
  https://api.gateway.ethswarm.org`, any browser, every chunk fetched from
  the network): ready in 7.5 s, `fruit` 6.5 s, `food` 2.9 s, `get fruit`
  3.0 s, all answers equal to the native reader's. That is the network's
  latency per level of the trie, paid once per session.

**Cone summaries, published (later the same night).** A broad query
still walked its cone: `get physical-object` read 2,443 records (6,753
chunk reads for the check's session). `publish_index.py` rebuilds each
pack under Swarm addressing (its root must equal the pinned one) and
publishes its summaries (`ontodag.cones`; 46 to 68 categories per pack,
about 30 s each). The page pins the eleven index roots and
`open_published(..., index_root=)` hands them to the reader.

| | without the index | with it |
|---|---|---|
| `get physical-object` (2,509 found) | 2,443 records read | none |
| the check's session | 6,753 chunk reads | 414 |
| real Freedom, connected | not measured | 155 ms (first visit), 65 ms (second) |

The index is a cache in the page: one for another root is ignored, and
one the page cannot fetch is a miss (`_CacheOnly` keeps the reason), so
the reader walks, exact either way.

**Erasure coding, found by the index.** Bee 2.8 erasure-codes `/bytes`
uploads without a `swarm-redundancy-level` header: a 10 KB upload's root
chunk carried `0x81` in its span's top byte, against the plain content
address with level 0. recordstore's `BeeBytesStore` sends no level
(swarmfs's `redundancy=None`, the node's default). So every store written
through it, loopmarket's books and the first index among them, has coded
trees for its blobs over 4 KB. Those references are not recordstore's
Swarm addressing, and the page's joiner refused them. The packs went up
through the local-first path, which requires level 0, so their roots are
the pinned ones.

`swarm.js` now joins coded trees: it reads a coded chunk's data
references only, their count from the span and the level's table, after
bee's `ReferenceCount`. It was checked against trees the node coded at
levels 0 to 4 (`test/make_coded.py`). Whether `BeeBytesStore` should
upload plain by default (references equal to Swarm addressing, and
checkable offline) or keep the node's coding (durability) is Peter's
question.

Next, as §8 orders them: writing under the §11 key (Weeb-3 or an HTTP
node first, Freedom after #647). The gateway step is done (above).

**Pyodide in a shared folder (2026-10-12).** Pyodide's core is 3,279 of a
page's roughly 3,400 chunks, and every page publish stamped it again. A
page at one `bzz://` address loads Pyodide from another, as a test in real
Freedom showed (Python 3.12.7 running in 3.6 s from
`bzz://e0f26cbb…/pyodide/`). So both pages now load Pyodide from one
shared folder:
- in Freedom, at `bzz://PYODIDE/`;
- served by a node, at its own `/bzz/PYODIDE/`;
- otherwise, through the gateway.

A page publish is then its own files and wheels, about 0.5 MB, and a
browser caches Pyodide once for both pages and every version.
`build.py --pyodide-only` publishes the folder; until it has its own
address, `PYODIDE` names the copy inside the published ontodag page.
Which batch carries it is Peter's question.

## 14. Local files, and writing to Swarm (2026-10-12)

Both pages are read-only. They read published stores from Swarm and write
nothing but their cache of checked chunks. Two kinds of writing were looked
at: a store kept in a local file (organising your own things without
Swarm), and writes to Swarm, which need stamps.

### 14.1 Local files

A page never reaches files on its own; the person grants each file or
folder. There are three ways, and a probe page (`bzz://65964c7d…`, one
button per case) tried them in real Freedom from its checkout (Electron
44.7):

| way | in Chromium (Chrome) | in Freedom (2026-10-12) |
|---|---|---|
| **file pickers that save back in place** (File System Access: `showOpenFilePicker`, `showSaveFilePicker`, `showDirectoryPicker`) | yes | the APIs exist and the dialogs open, but **every access after the pick is refused**: reading a picked file `NotAllowedError`, writing back "denied", writing a new file `NotAllowedError` |
| **open by a file input, save by a download** | yes | a download of a generated `.od` went silently to the profile's downloads folder; the file input not yet tried |
| **the browser's private storage** (OPFS, IndexedDB) | yes | yes: a file written and read back in OPFS, about 117 GB of quota, not persistent unless granted |

- **Why Freedom refuses:** Electron raises a `fileSystem` permission
  request after a pick (with the path and `readable` or `writable`), and
  Freedom's handler (`src/main/permissions/permissions-manager.js`)
  refuses any permission it does not list. Supporting it would be a Freedom
  change: a per-site prompt for `fileSystem`, as it has for the camera.
- **Brave** turned File System Access off on purpose (brave-browser#11407)
  and offers only a global flag (`brave://flags/#file-system-access-api`).
  Peter ran the probe through a node (`http://localhost:1633/bzz/65964c7d…/`):
  no picker opens at all. Firefox and Safari have no pickers either.
- **Private storage is shared under a node's origin.** Every page opened
  through `http://localhost:1633/bzz/…` is the same origin, so anything one
  keeps in IndexedDB or OPFS is readable by every other Swarm page opened
  through that node. Under Freedom (`bzz://NAME/`) or `NAME.gwei.domains`
  each name is its own origin. Anything private belongs in real files.

What it means for the pages:
- **ontodag:** your own store as an `.od` file, with ontodag running whole
  under Pyodide (`put`, `get`, `rename`, merge) and the packs still read
  from Swarm; adopting a pack is the merge it already is. Saved in place
  where the pickers work (Chrome), and by open and download elsewhere,
  Freedom included. With a folder picked, the page could list its files
  and file them under categories; only the store is written.
- **loopmarket:** drafting offers into a local book file works the same
  way; publishing them is a Swarm write (14.2) under the §11 key.

**Built (2026-10-12):** the ontodag page keeps your own store in a local
file (`ontodag.browser.LocalStore`, a whole `OntoDAG` in memory):
- **Writes:** New or Open file, Put, Remove (contraction, as `odag
  remove`), the prelude, and browsing and `get` as with a pack. Typed
  relative times are read with the clock.
- **Save:** writes `.od` text, the format `odag` reads (`check.py`
  compares it byte for byte). It goes back to the same file where the
  pickers work (Chrome), and is a download where they are refused
  (Freedom, detected and remembered) or missing (Brave, Firefox, Safari);
  Open then uses a file input.
- The page warns before leaving with unsaved changes, and `check.py`
  drives the whole path through the page's buttons in Chromium.

**Requests filed** (2026-10-12; drafts in `../upstream-issues/`):
- **Freedom #671:** treat `fileSystem` like the camera. Grant reading what was
  picked, prompt per site for writing, and keep Electron's restricted
  locations blocked.
- **Brave #59862:** make File System Access a per-site permission instead of a
  global flag. Its tracker has the removal (#11407), the flag (#18979,
  #44411) and the TypeError (#29411), but no per-site request.

**A local file as a buffer for Swarm writes.** It fits a store:
- **Why:** merge is a CRDT (I7), so edits made offline, saved locally and
  published later converge with what others published meanwhile. Nothing is
  lost or ordered wrongly by the delay, and the file is the copy the person
  owns.
- **Publishing:** writes its root under the person's feed (§11).

It does not fit an offer, or anything that is a commitment to others:
- **Why:** an offer means something only from when it is published, and
  only while its terms (prices, times, places) still hold. A draft offer
  in a file is a note to oneself, not an offer.
- **Publishing:** `loop` signs and announces it directly. A page should
  say so, rather than queue offers behind a later sync.
- Withdrawals and fills are the same: they must reach the book when made.

### 14.2 Writing to Swarm: who pays for the stamps

Four routes, each with its own way of paying:

- **Freedom's `window.swarm`** (read from its source, not yet exercised by
  a page of ours):
  - **The methods:**
    - `swarm_publishData` (up to 10 MB), `swarm_publishFiles` (up to 100
      files, 50 MB) and `swarm_publishChunk` (4 KB);
    - `swarm_writeSingleOwnerChunk`;
    - `swarm_createFeed`, `swarm_updateFeed` and `swarm_writeFeedEntry`;
    - `swarm_sendPss` and `swarm_sendGsoc`.
  - **Permission:** each needs `swarm_requestAccess` and a prompt per call
    unless the site was given "Always allow". The provider is on only with
    the `enableIdentityWallet` setting.
  - **Stamps: the page never sees a batch.** Freedom's main process picks
    one of the node's usable batches (enough room with a 1.5× margin, the
    longest TTL first).
  - **Buying:** with its own node (Ant), the user sends xDAI to the node's
    wallet and Freedom swaps it to xBZZ and buys an immutable batch. The
    plans are depth 20 for 30 days, 21 for 180 and 22 for 365. With a
    reused or external node, Swarm Desktop for instance, Freedom does not
    buy: pages publish with that node's batches, bought in that node's
    own tooling.
  - **Feeds:** the topic is per origin (`origin/name`). The signer is
    chosen when feed access is granted: a key for the site (the
    default), the node's wallet, or one of the user's Ethereum accounts.
  - **Budgets:** writes have none per minute, unlike reads; only the size
    caps, the prompts and the room left in the batch.
- **Swarm Desktop (a Bee node over HTTP).** Its dashboard buys batches
  with the node's wallet, and anything that talks to the node's API chooses
  a batch by its id (`Swarm-Postage-Batch-Id`), as our scripts do. A page
  opened through the node (`http://localhost:1633/bzz/…`) is the same
  origin as that API, so it can list the node's batches and upload with
  them, with no prompt at all (checked: the probe page, opened that way in
  Chromium, listed both of this node's batches with `fetch("/stamps")`). That is the route for a page today without
  Freedom, and the hazard of 14.1 again: any Swarm page opened that way can
  spend the node's stamps.

  The hazard is wider than Swarm pages (checked 2026-10-13). Swarm Desktop
  configures its node with `cors-allowed-origins: '*'` and no `restricted`
  mode. The node answers every origin: a request sent as from
  `https://example.com` got both batches back, the origin echoed. So any
  website open in a browser on the same computer can read the node's API
  and upload with its batches, unless the browser refuses to let public
  sites reach localhost.
- **Public gateways, with no stamp of one's own** (Andras's point,
  confirmed 2026-10-12): `https://api.gateway.ethswarm.org` and
  `https://bzz.limo` both accepted `POST /bytes` with no batch:
  - **Size:** 40 bytes, 1 MB, 5 MB and 11 MB were all `201`.
  - **Pages may use them:** `Access-Control-Allow-Origin: *` on both.
  - **Equal bytes, equal reference:** the same test text gave
    `cca8a06d…` at both.
  - **It lands:** the text was retrievable through this laptop's node at
    once, and the 1 MB upload through api.gateway within minutes.
  - **Not yet known:** whether the 11 MB uploads land (not retrievable
    within 5 minutes), and how long gateway-stamped data lives ("short
    term"). Recheck the references below a day and a week later.
  - **A day later** (2026-10-13): api.gateway served all five whole.
    This laptop's node found the text and both 1 MB uploads retrievable
    from the network (`/stewardship`). For the 11 MB ones, the check gave
    no answer within 9 minutes. It walks every one of their roughly 2,800
    chunks, so that settles nothing either way; recheck in a week.

  For a page with no node and no stamps, that is a way to write something
  small for a while (a draft, a share link), but not to keep a store.
- **Your own batch, through a gateway.** According to Swarm ID's notes
  (measured 2026-09-15, not by us), api.gateway does three different
  things with a stamp:
  - a `POST /chunks` carrying a stamp the caller made is accepted and
    spends the caller's batch;
  - `POST /bytes` ignores a batch id and spends the gateway's own batch;
  - `POST /bytes` refuses a caller's stamp.

  So a page with no node can keep a store: it chunks the blobs itself,
  stamps them with a batch the person owns, and sends them chunk by chunk.
  That is how Swarm ID uploads, and dappdata's stamper (whose own spike
  sent such chunks to a node) would work the same way.

Gateway test references (2026-10-12), to recheck for lifetime:

| what | reference | through | a day later: api.gateway / the network |
|---|---|---|---|
| 40-byte text | `cca8a06d04f8be1d548efc3ecc6682c3003dbd2ab064d4a5c3e07979f8d46826` | both | served / retrievable |
| 1 MB random | `8f1debd0d582ee58f2540c9fb363e049d6489e806e841ba8b0139d29b2afbe51` | api.gateway | served / retrievable |
| 11 MB random | `d49a090f872576de6290b1ef6df21f2edad925b5f02299ca08266732bf1df689` | api.gateway | served / no answer in 9 min |
| 1 MB random | `731cfda96ec268b8a041ae8e0890a128fcab6323b21f360acd9e4acc1fabd169` | bzz.limo | served / retrievable |
| 11 MB random | `639f4be84af945a3119eeb673805b5cb8c0f63c8c615ca6879309c442858ab0b` | bzz.limo | served / no answer in 9 min |

Decided (Peter, 2026-10-13): question 37, writing the installed way first
(14.3).

Decided (Peter, 2026-10-12): local files first, built above.

### 14.3 Swarm ID (2026-10-13)

Peter: "others are working on swarmID". Swarm ID (snaha/swarm-id, 0.7.0
released 2026-10-12, read from its docs that day) covers much of what
writing needs:
- **The account:** a recovery phrase on the identity site
  (`swarm-id.snaha.net`), which a page reaches through a hidden iframe and
  a connect popup. A wallet, a passkey or a password unlocks it on each
  device. The wallet does not derive the key; it unlocks a random seed
  kept on the device.
- **Keys:**
  - each app gets a secret derived from its origin (`HMAC(master,
    origin)`), with an app key that signs its feeds and single-owner
    chunks by default;
  - `deriveAppSecret(label)` gives an app further key material;
  - one account-wide sharing key, of which apps see the public half; Bee's
    ACT uses it inside Swarm ID.
- **Stamps:**
  - batches owned by the account's postage signer, bought on the identity
    site (with xDAI, or by card through a shop);
  - one batch shared across devices without reusing a slot;
  - uploads go through the public gateway (14.2) or the person's own node,
    or through a gateway that pays for the app.
- **Writes:** chunks, single-owner chunks, sequential and epoch feeds
  (the writers take another signer's private key too), ACT, files.
- **Where it runs:** the authors tested Safari on iOS, uploads included.
  Freedom is not mentioned anywhere in its repository.

**How it fits §11 (decision A) and the pages:**
- **The owner depends on the address.** Every origin is another app, so
  the same person opening `bzz://ontodag.eth` in Freedom,
  `ontodag.gwei.domains` and `localhost:1633/bzz/…` gets three app keys,
  and so three owners of "your store". Writing would have to be pinned to
  one address. loopmarket's maker (offer signer, book owner and registry
  announcer in one) has the same problem.
- **The sharing key is out of reach.** It works only through Swarm ID's
  own ACT, and the page sees only its public half. ontodag's sharing
  (`keyplan`, §12) needs the page to do the ECDH itself.
- **The desktop:** `odag` and `loop` are the same person only through a
  port of its derivation from the recovery phrase. Its docs give the
  recipe.
- **Trust:** the identity site is a hosted service. dappdata stayed
  independent of it for that reason (its D8). Its D24 proposed one
  derivation spec for both, sent in September, unanswered when last
  checked.

What it would save us is the hard part of 14.2: buying a batch, stamping
in the page, devices sharing a batch, and writing with no node.

**Decided (Peter, 2026-10-13):**
- **Question 37: the installed way first, identity later.**
  - **The way:** a page writes as `odag` and `loop` do. A random key owns
    the feeds and signs, and the node's batches pay: Swarm Desktop over
    HTTP now, Freedom's once #647 lands.
  - **The rule that avoids lock-in:** the key that owns a store or a book
    stays the same. Identity, from a wallet signature (dappdata) or from
    Swarm ID, comes later as the way that key is carried and recovered on
    a new device, not as a new key.
  - **So the convergence talk (dappdata D24) is not urgent.** A later
    derivation changes how the key is found, not who owns anything. Paying
    with a batch the person owns, for writing without a node, waits on the
    same talk.
- **Question 38: the key file is plain for now.** It holds the key as hex,
  the `bee_signer` value `odag` keeps in its config. A password-protected
  file in the Ethereum keystore format (the one Bee keeps its own key in)
  comes later, once the pages are more than a demo. Whoever holds the
  plain file can write that person's feeds.

The page never stores the key. It is opened from the file when needed and
held in memory, so it does not land in the storage that every page opened
through `localhost:1633` shares (14.1).

## 15. iPhones: reading by retrying (2026-10-12)

**The failure.** Meinhard opened the market page in Freedom on an iPhone
and got "JavaScript frames found between WebAssembly.Suspending and
WebAssembly.promising" instead of the market. JSPI suspends only a stack
of WebAssembly frames, and on iOS Pyodide (0.27.7) puts a JavaScript frame
on it. CPython calls C function pointers through a trampoline, and
Pyodide's start-up (`getPyEMCountArgsPtr`) takes the JavaScript trampoline
when `navigator.platform` names an iPhone, iPad or iPod, or when wasm-gc is
missing. Pyodide's blog (2025-08-14) says wasm-gc crashes on iOS, so a
newer Pyodide is unlikely to change it. Chromium reporting an iPhone's
platform reproduces it exactly, and in V8 the failed suspension is fatal
to Pyodide ("Pyodide already fatally failed"), so a page cannot try JSPI
and fall back.

**Reading by retrying** (`ontodag.browser.RETRY`, `NeedBlobs`,
`RetryingPage`; the page's `pycall.js`):
- Python never waits on a promise. It reads only blobs the page has
  already fetched (`BlobStore.cached`).
- A call that reaches a missing blob stops with `NeedBlobs` (a
  `BaseException`, so no `except Exception` on the way out mistakes it for
  a failure), naming every blob it lacked at that point.
- The page fetches them (`BlobStore.fetch`) and runs the call again, on a
  fresh reader, so a run cut short leaves no half-read state behind.
- A blob whose fetch failed stays an error, never "absent", until the next
  action tries it again.

**Which mode** (`PythonCalls.choose`, never by trying a suspension):
- `?bridge=jspi` or `?bridge=retry` names one;
- without `WebAssembly.Suspending`, retry;
- where Pyodide's count-args helper is 0 (`Module._PyEM_CountArgsPtr`:
  the JavaScript trampoline), retry;
- otherwise JSPI, as before.

**Cost.** Retrying makes the same network round trips as waiting, plus one
final run (tests: 117 runs for a cone the waiting bridge read in 119
calls), because each run stops at the first level it lacks, as the waiting
bridge would have fetched it. What retrying adds is computation: each run
walks again from the start over blobs already held. Measured in Chromium
on core, emulating an iPhone: `fruit` with its 35 children in 1.0 s
against 0.8 s waiting. A loopmarket book absorbs record by record, so its
fold needs about one run per blob; today's books are a few chunks.

**Found on the way.** `LazyOntoDAG._expand` marked a node expanded before
reading its record, so a read that failed left an edgeless stub that the
next query took for a node with nothing below it. That was fail-open with
an unreachable blob too, before retry mode existed. Fixed (the record is
read first), with a test that failed before.

**Checked:**
- both pages' `check.py --iphone`: Chromium reporting an iPhone's
  platform, so Pyodide takes the JavaScript trampoline;
- the page chooses retry, and every answer equals the native reader's,
  your own store and saved searches included;
- without `--iphone` the page keeps JSPI.

Not yet seen on a real iPhone: Meinhard's next visit is the test. Playwright's
WebKit needs a system library here (`libavif16`).

## 16. Publishing your store, the installed way (2026-10-13)

Built on questions 37 and 38 (§14.3): the ontodag page writes your own
store to Swarm as `odag -f swarm:NAME` does. A random key in a plain file
owns the store's feed, and the node that served the page pays from its
batches.

**In the page** (`demo/freedom/publish.js`, the "On Swarm" row under your
own store):
- **The key.** New key makes one and downloads it (`0x` and 64 hex
  digits, the `bee_signer` value `odag` keeps), and Open key file reads it
  back. The page holds it in memory and shows only its address. Signing
  is noble-curves 1.9.7 (vendored beside noble-hashes): a feed update the
  page signs is byte for byte the one swarmfs signs with libsecp256k1
  (`test/feed_vector.json`, made by `test/make_feed_vector.py`).
- **The blobs.** Python commits the store through `StagedBlobs`: each blob
  it writes goes to the page's `Stage`, which computes its Swarm reference
  for a plain upload (`swarm.js` `contentAddress`, checked against the
  splitter's trees from 0 to 600 KB) and keeps it. Writing needs no
  bridge, so it works in retry mode too.
- **The commit**, as `odag`'s save makes it (`LocalStore.publish`):
  - **onto the root the store descends from** when the feed still holds
    that root, or nothing: the store goes up as it is, removals included;
  - **folded first** when the feed moved on (another device, or `odag`
    with the same key) or when the store came from a file: the union, as
    `EagerOntoDAG.sync` folds a moved head. A removal made here comes back
    if the feed still has it, as on the command line. The page names what
    came in and marks the file out of date.

  Same knowledge, same root as `odag`'s (tests).
- **Upload, then the feed.** Every staged blob not yet confirmed goes to
  the node's `POST /bytes`:
  - plain (`Swarm-Redundancy-Level: 0`) and pushed before the answer
    (`Swarm-Deferred-Upload: false`);
  - the node's reference must equal the page's;
  - each must then be retrievable (`/stewardship`) before the feed moves.

  Then the feed update in recordstore's format (time and root, signed by
  the key) goes to `POST /soc` at the next index. The page finds the
  newest index by probing the updates themselves, as `SwarmFeedPointer`
  does, checks that its signature recovers to the owner, and reads the
  new root back.
- **Get from Swarm** folds the feed's newest root into the store you have
  (`LocalStore.fetch`). A new store becomes exactly the published one:
  that is opening your store on another device. It needs only the key
  file (for the address), and works wherever the page reads Swarm,
  Freedom and gateways included.
- **Retry mode:** `publish` and `fetch` read everything a fold needs
  before changing anything (`_read_first`), so a run that stops for
  missing blobs (`needing`) leaves the store as it was.

**Checked:**
- **Tests** (`TestPublishingYourStore`, 8):
  - the root is the one `odag` commits under Swarm addressing, and the
    blobs uploaded alone read back to the same store;
  - an unmoved feed takes the store as it is, removals included, and an
    unchanged store stages nothing;
  - a feed written elsewhere is folded in, and a removal comes back when
    the feed still has it;
  - a store from a file is folded with the feed, and a new store fetched
    is the published one;
  - an empty store is not published;
  - in retry mode nothing changes, and nothing is staged, until every blob
    is fetched, and the root is then the waiting bridge's.
- **`test_publish.mjs`:**
  - a feed update byte for byte swarmfs's, its signature libsecp256k1's,
    recovering to the owner;
  - blob addresses from 0 to 600 KB equal to the splitter's.
- **`check.py --publish`** (2026-10-13). Chromium ran the page through the
  stand-in for Freedom's provider, writing through this laptop's node
  (`?node=`), with a throwaway key on `c931c8a5…`:
  - the page published a store (`fruit`, `apple`) in 10 s (root
    `a366e5a9…`), read back natively, feed and store;
  - `odag -f swarm:NAME put pear fruit`, in its own home with the same
    key, moved the feed (22 s);
  - the page, not told, put `plum` and published again: it folded the
    pear in (root `39a16628…`, feed update 3) in 18 s;
  - `odag` in a fresh home read `apple pear plum` from the feed (40 s);
  - a new store in the page got the same from Swarm.

  With `--bridge retry` (the iPhone path) the same, to the same roots.

**Where it publishes:**
- a page opened through a node (`http://localhost:1633/bzz/ontodag.eth/`
  with Swarm Desktop), or one told `?node=URL`;
- the batch is chosen in the page from the node's usable ones, longest
  life first.

Freedom waits for #647; until then the page says so, and Get from Swarm
works there. A gateway has no batches to choose.

**Not yet:**
- a password-protected key file (question 38's later step);
- the identity that carries the key (question 37);
- Freedom (#647);
- loopmarket's maker page, which needs the same key, stage and writer
  (its BROWSER.md §5).

A first publish of a store from a file rebuilds it whole, and a fold from
a file reads the whole published store: fine for a person's store, and
the next publish from the same session commits only what changed.

## 17. The page as a personal organiser (2026-10-13)

**Peter's direction (2026-10-13).** OntoDAG is mainly useful for
organising your own information, and the page should be reorganised for
that:
- the shared ontology moves behind a menu item;
- the page helps people start organising, offering existing categories
  as they type;
- a personal folder can be opened and its files filed, tagged by file
  type to begin with, with more help later;
- any combination of stores can be shown together, not one at a time.

A clickable mockup shows the design with example files and an example
store; every category name and place in it is real, from core and
computing: https://claude.ai/artifact/TaqyGVRCfsky1CZLp76vfH (private
to Peter). Nothing of it is built in the page yet.

**The design (proposed):**
- **It opens on your store:** New store, Open store file, Open a folder.
  The packs move behind one menu, "Vocabularies", from which they can be
  shown or browsed.
- **One box for filing, with suggestions:** your categories first, then
  the vocabularies', each with where it sits. The place is shown because
  it matters: core's `photograph` is under `image` and `physical-object`
  (a print), so a jpg filed there would become a physical object.
- **A folder is read, never written.** Each file is tagged by its type:
  - jpg, png, heic, gif and webp under `image-file`;
  - mp4, mov and mkv under `video-file`;
  - mp3, m4a, wav and flac under `audio-file`;
  - txt, md, yaml and csv under `text-file`;
  - zip, gz and tar under `archive-file`, all from computing;
  - pdf, doc, docx, odt and the spreadsheets under core's `document`;
  - pptx and odp under core's `presentation`.

  Core's `spreadsheet` is the program (under `computer-program`), so
  spreadsheets go under `document` for now. The tags are the folder's
  layer (PROJECTIONS.md §3): rebuilt whenever the folder is opened, never
  written into your store, which holds only what you filed. The work
  list is "not yet filed"; several files are filed at once. Dates and
  folder names are the next easy tags.
- **Holdings' names:** in store terms a type tag is holdings'
  `sys:type:<ext>`, and a small table puts each under its kind
  (`sys:type:jpg ⊑ image-file`), so holdings' projection gets the same
  hierarchy (PROJECTIONS.md §8). Proposed, not decided.
- **Any combination of stores:** ticked vocabularies, a published root
  or another store are read together with yours, and only yours changes.
  This is `odag`'s overlay view (`Session.view()`, PROJECTIONS.md §5)
  brought to the page. Browsing starts from your categories, and a
  vocabulary's categories show only around the ones you use.
- **Reading a folder:** a plain folder input (`<input type="file"
  webkitdirectory>`) gives the page the folder's list read-only: names,
  paths inside the folder, sizes, dates. That is expected in Chrome,
  Firefox and desktop Safari; Brave and Freedom are to be probed (what
  Freedom refused, §14.1, was File System Access). After a reload the
  folder is picked again. The page never sees a file's absolute path,
  only its path inside the folder picked.

**Question 39 (decided A, Peter, 2026-10-13): when you pick a
vocabulary's category, only its name goes into your store.** Filing
`rome-001.jpg` under core's `holiday` stores `rome-001.jpg ⊑ holiday`;
with core shown, `get event` finds the photo. The page shows a
vocabulary by itself when your store or the folder uses its names,
unless you turned it off. Read alone (`odag` without the `overlays`
setting), such a name is one of your top categories. Rejected:
- **B:** copying the name's ancestors (7 for `holiday`). Core's top
  branches would fill your top, and copied edges never get a vocabulary's
  sense corrections, which do not travel by merge.
- **C:** copying its direct parents only. It leaves a partial chain, with
  the same problem.

**Hashing in the page, measured (2026-10-13, this laptop, headless
Chromium, 128 MB of random bytes, three runs):**

| how | speed |
|---|---|
| `crypto.subtle.digest` (the whole file in memory) | 214–219 MB/s |
| the same over 4 MB files | 214–219 MB/s |
| noble's streaming SHA-256 (for files too big to hold) | 64–66 MB/s |
| native Python `hashlib`, for comparison | 259 MB/s |

Reading the files from disk comes on top.

**Open:** question 40 (what a file is called in your store) and
question 41 (where your store lives between visits).
