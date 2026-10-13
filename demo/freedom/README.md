# OntoDAG on Swarm, in the browser

An organiser for your own things (BROWSER.md §17). Python (ontodag and
recordstore) runs under Pyodide.
- **Your store** is a local `.od` file, the format `odag` reads: saved
  back in place where the browser allows it (Chrome), downloaded where it
  doesn't (Freedom, Brave), and published to Swarm when you choose, as
  `odag -f swarm:NAME` does, through the node that served the page and
  under a key you keep in a file.
- **The vocabularies** (the packs, shipped beside the page as
  `packs.json`) are shown beside it in any combination. While you type,
  they suggest names with where each sits, core's also by its WordNet
  words.
- **A published store** can still be browsed read only, straight from
  Swarm, through Freedom Browser's `window.swarm` or a Swarm node or
  gateway over HTTP, nothing downloaded whole.

Design and measurements: `docs/plans/BROWSER.md` §10–§17.

Stable address (a feed manifest; every publish advances the feed, so it
always opens the current version): `bzz://eaaa79002b255222218984bc54a73131adcf720180f06542c1c8e176973a2a23/`. The publisher key is
`~/.ontodag/page-feeds/ontodag.key` on the publishing machine (never
committed); `ontodag/demo/freedom/page_feed.py` makes and moves the feed.

Names: `bzz://ontodag.gwei/` in Freedom Browser, `https://ontodag.gwei.domains/`
in any browser, and `http://localhost:1633/bzz/ontodag.eth/` with a local Bee
node such as Swarm Desktop, no gateway (all resolve the feed; `../DOMAINS.md`
beside the repos).

Published, behind the names since 2026-10-14 (feed update 7): the
organiser (BROWSER.md §17) built from the 0.33.0 release, with Publish
(§16), the save help (§14.1) and the Android fixes, `bzz://c9e24c73b8f1f0f304d7f7498131e679a106be93e03ec33ee46d185f0e279380/`
(Pyodide loaded from the shared folder `PYODIDE` in `app.js`; through a
node: `http://localhost:1633/bzz/c9e24c73b8f1f0f304d7f7498131e679a106be93e03ec33ee46d185f0e279380/`, which is also where Publish
works; in any browser, through the public gateway,
serve `dist/` and add `?gateway=https://api.gateway.ethswarm.org`). The
versions before it were `bzz://44bb7def0aad9712c282bf17de4757a33d95ac5becba59eb8866a32008393847/` (update 6) and
`bzz://22d1e16bebfd0afccdddb2060b5669f68c26b66c19d94cd58eb1d992bfc74d8a/` (update 5).

| file | what it is |
|---|---|
| `index.html`, `app.js` | the page: your store first (New, Open, Save; Add with suggestions, a category's page with above, below and about, Put under, Remove, Find), the vocabularies shown beside it (`ontodag.browser.Organiser`), Publish and Get from Swarm under a key file, and a published store browsed read only (by its pinned root: a category with what is above and below it, `get`, `below`) |
| `packs.json` | made by `build.py`, not kept here: every pack's canonical text, for the vocabularies (loading text is ten times quicker than building a pack in the page) |
| `publish.js` | writing your store (BROWSER.md §16): the key (`Key`, signing as Bee checks), the `Stage` Python's `StagedBlobs` writes into, `NodeWriter` (the node's batches, plain uploads, `/stewardship`, the feed found by probing and written with `POST /soc`) and `uploadStaged` |
| `pycall.js` | how Python waits for Swarm: JSPI, or retrying where JSPI cannot suspend Python (Pyodide on iOS; BROWSER.md §15) |
| `localfile.js` | opening and saving a local file: in place where the browser allows it, by file input and download elsewhere |
| `savehelp.js` | where Save can only download (Brave, Freedom, Firefox, Safari): a dialog naming the browser's ask-where-to-save setting, its address copied to paste, and in Brave the File System Access flag, offered only after a yes (BROWSER.md §14.1); `node test/test_savehelp.mjs` checks which help each browser gets |
| `swarm.js` | the Swarm layer: `FreedomSwarm`, `HttpSwarm`, `ChunkReader` (chunk trees joined, every chunk checked against its address, an IndexedDB cache), `BlobStore` for Python |
| `vendor/noble-hashes/` | keccak-256 and the hashes secp256k1 needs (MIT), as `swarm.js` and `publish.js` import them |
| `vendor/noble-curves/` | secp256k1 (MIT, 1.9.7), for `publish.js` |
| `build.py` | assembles `dist/` (the page and wheels built from this checkout and recordstore's, about 0.5 MB); `--publish --batch ID` uploads it to a Bee node. Pyodide is not in it: the pages load it from its own folder on Swarm (`app.js`, `PYODIDE`), published once with `--pyodide-only`; `--bundle-pyodide` puts a copy in instead |
| `check.py` | runs `dist/` in Chromium against a Bee node and compares every answer with Python reading the same root: through a stand-in for Freedom's provider (default), the node over HTTP (`--url`), or a gateway (`--gateway`); then drives your own store through the page's buttons (new, put, save by download, open by file input, remove). `--bridge retry` forces reading by retrying; `--iphone` reports an iPhone's platform, so the page runs as on iOS. `--publish` (with `BEE_BATCH`) also publishes a store under a throwaway key and checks it against `odag` with the same key: read back natively, `odag` adds to it, the page folds that in, a fresh `odag` reads the union, and a new store gets it from Swarm |
| `freedom_check.cjs` | runs the published page in real Freedom Browser from a Freedom checkout (`node freedom_check.cjs REF [--connect]`) |
| `publish_index.py` | publishes packs' cone summaries (`ontodag.cones`) for the page to pin: a broad category in one record instead of a walk |
| `test/` | `swarm.js` checked against swarmfs's splitter: `python3 test/make_vectors.py > v.json && node test/test_swarm.mjs v.json`; with `BEE_BATCH`, `test/make_coded.py > c.json` adds trees the node erasure-coded at every level (`node test/test_swarm.mjs v.json c.json`). `publish.js` checked against swarmfs's signer and splitter: `node test/test_publish.mjs test/feed_vector.json v.json` (the vector made by `test/make_feed_vector.py`) |

The page needs recordstore's `RecordStore.get_many` (unreleased until the
next recordstore release); `build.py` builds recordstore from its checkout.
