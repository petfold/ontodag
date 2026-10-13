# OntoDAG on Swarm, in the browser

A page that reads a published ontology straight from Swarm: Python
(ontodag and recordstore) runs under Pyodide, and Swarm is reached through
Freedom Browser's `window.swarm`, or through a Swarm node or gateway over
HTTP. Nothing is installed and nothing is downloaded whole. It also keeps
a store of your own in a local `.od` file (the format `odag` reads): saved
back in place where the browser allows it (Chrome), downloaded where it
doesn't (Freedom, Brave), and published to Swarm when you choose, as
`odag -f swarm:NAME` does, through the node that served the page and under
a key you keep in a file. Design and measurements: `docs/plans/BROWSER.md`
§10–§16.

Stable address (a feed manifest; every publish advances the feed, so it
always opens the current version): `bzz://eaaa79002b255222218984bc54a73131adcf720180f06542c1c8e176973a2a23/`. The publisher key is
`~/.ontodag/page-feeds/ontodag.key` on the publishing machine (never
committed); `ontodag/demo/freedom/page_feed.py` makes and moves the feed.

Names: `bzz://ontodag.gwei/` in Freedom Browser, `https://ontodag.gwei.domains/`
in any browser, and `http://localhost:1633/bzz/ontodag.eth/` with a local Bee
node such as Swarm Desktop, no gateway (all resolve the feed; `../DOMAINS.md`
beside the repos).

Published: `bzz://22d1e16bebfd0afccdddb2060b5669f68c26b66c19d94cd58eb1d992bfc74d8a/`
(2026-10-12; Pyodide loaded from the shared folder `PYODIDE` in `app.js`;
through a node: `http://localhost:1633/bzz/22d1e16bebfd0afccdddb2060b5669f68c26b66c19d94cd58eb1d992bfc74d8a/`;
in any browser, through the public gateway, serve `dist/` and add
`?gateway=https://api.gateway.ethswarm.org`).

Next version, with Publish (BROWSER.md §16) and the save help (§14.1),
not behind the names yet: `bzz://89a9deed695fb4d841e0d2e5d938109c9571b7ab2fc2353251e80f871f68abb8/`
(2026-10-13; to publish, open it through your node:
`http://localhost:1633/bzz/89a9deed695fb4d841e0d2e5d938109c9571b7ab2fc2353251e80f871f68abb8/`).

| file | what it is |
|---|---|
| `index.html`, `app.js` | the page: a store (the published packs by their pinned roots, or your own in a local file), a category with what is above and below it, `get`, `below`; for your own store, put, remove, the prelude and save, and on Swarm a key file, Publish and Get from Swarm |
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
