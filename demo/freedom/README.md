# OntoDAG on Swarm, read-only, in the browser

A page that reads a published ontology straight from Swarm: Python
(ontodag and recordstore) runs under Pyodide, and Swarm is reached through
Freedom Browser's `window.swarm`, or through a Swarm node or gateway over
HTTP. Nothing is installed and nothing is downloaded whole. Design and
measurements: `docs/plans/BROWSER.md` §10–§13.

Published: `bzz://e0f26cbbcf0985f518fc6ffcdcad9d6ff121b1a5bd10deea6be430e83be7926a/`
(open it in Freedom Browser; through a node:
`http://localhost:1633/bzz/e0f26cbbcf0985f518fc6ffcdcad9d6ff121b1a5bd10deea6be430e83be7926a/`;
in any browser, through the public gateway, serve `dist/` and add
`?gateway=https://api.gateway.ethswarm.org`).

| file | what it is |
|---|---|
| `index.html`, `app.js` | the page: a store (the published packs by their pinned roots), a category with what is above and below it, `get`, `below` |
| `swarm.js` | the Swarm layer: `FreedomSwarm`, `HttpSwarm`, `ChunkReader` (chunk trees joined, every chunk checked against its address, an IndexedDB cache), `BlobStore` for Python |
| `vendor/noble-hashes/` | keccak-256 (MIT), as `swarm.js` imports it |
| `build.py` | assembles `dist/` (the page, Pyodide's core, wheels built from this checkout and recordstore's); `--publish --batch ID` uploads it to a Bee node |
| `check.py` | runs `dist/` in Chromium against a Bee node and compares every answer with Python reading the same root: through a stand-in for Freedom's provider (default), the node over HTTP (`--url`), or a gateway (`--gateway`) |
| `freedom_check.cjs` | runs the published page in real Freedom Browser from a Freedom checkout (`node freedom_check.cjs REF [--connect]`) |
| `publish_index.py` | publishes packs' cone summaries (`ontodag.cones`) for the page to pin: a broad category in one record instead of a walk |
| `test/` | `swarm.js` checked against swarmfs's splitter: `python3 test/make_vectors.py > v.json && node test/test_swarm.mjs v.json`; with `BEE_BATCH`, `test/make_coded.py > c.json` adds trees the node erasure-coded at every level (`node test/test_swarm.mjs v.json c.json`) |

The page needs recordstore's `RecordStore.get_many` (unreleased until the
next recordstore release); `build.py` builds recordstore from its checkout.
