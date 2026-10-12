# OntoDAG on Swarm, read-only, in the browser

A page that reads a published ontology straight from Swarm: Python
(ontodag and recordstore) runs under Pyodide, and Swarm is reached through
Freedom Browser's `window.swarm`, or through a Swarm node or gateway over
HTTP. Nothing is installed and nothing is downloaded whole. Design and
measurements: `docs/plans/BROWSER.md` §10–§13.

Stable address (a feed manifest; every publish advances the feed, so it
always opens the current version): `bzz://eaaa79002b255222218984bc54a73131adcf720180f06542c1c8e176973a2a23/`. The publisher key is
`~/.ontodag/page-feeds/ontodag.key` on the publishing machine (never
committed); `ontodag/demo/freedom/page_feed.py` makes and moves the feed.

Names: `bzz://ontodag.gwei/` in Freedom Browser, `https://ontodag.gwei.domains/`
in any browser (both resolve the feed; `../DOMAINS.md` beside the repos).

Published: `bzz://cc4c99b615eb886c6c8c5ccf8217a26ed8aa41f8452fdd4b2c1061496ad91468/`
(2026-10-12; Pyodide loaded from the shared folder `PYODIDE` in `app.js`;
through a node: `http://localhost:1633/bzz/cc4c99b615eb886c6c8c5ccf8217a26ed8aa41f8452fdd4b2c1061496ad91468/`;
in any browser, through the public gateway, serve `dist/` and add
`?gateway=https://api.gateway.ethswarm.org`).

| file | what it is |
|---|---|
| `index.html`, `app.js` | the page: a store (the published packs by their pinned roots), a category with what is above and below it, `get`, `below` |
| `swarm.js` | the Swarm layer: `FreedomSwarm`, `HttpSwarm`, `ChunkReader` (chunk trees joined, every chunk checked against its address, an IndexedDB cache), `BlobStore` for Python |
| `vendor/noble-hashes/` | keccak-256 (MIT), as `swarm.js` imports it |
| `build.py` | assembles `dist/` (the page and wheels built from this checkout and recordstore's, about 0.5 MB); `--publish --batch ID` uploads it to a Bee node. Pyodide is not in it: the pages load it from its own folder on Swarm (`app.js`, `PYODIDE`), published once with `--pyodide-only`; `--bundle-pyodide` puts a copy in instead |
| `check.py` | runs `dist/` in Chromium against a Bee node and compares every answer with Python reading the same root: through a stand-in for Freedom's provider (default), the node over HTTP (`--url`), or a gateway (`--gateway`) |
| `freedom_check.cjs` | runs the published page in real Freedom Browser from a Freedom checkout (`node freedom_check.cjs REF [--connect]`) |
| `publish_index.py` | publishes packs' cone summaries (`ontodag.cones`) for the page to pin: a broad category in one record instead of a walk |
| `test/` | `swarm.js` checked against swarmfs's splitter: `python3 test/make_vectors.py > v.json && node test/test_swarm.mjs v.json`; with `BEE_BATCH`, `test/make_coded.py > c.json` adds trees the node erasure-coded at every level (`node test/test_swarm.mjs v.json c.json`) |

The page needs recordstore's `RecordStore.get_many` (unreleased until the
next recordstore release); `build.py` builds recordstore from its checkout.
