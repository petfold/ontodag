"""End-to-end check of the read-only page, outside the suite (like
scripts/browser_check.py): Playwright's Chromium runs the page from
demo/freedom/dist/ and reads a published pack from a real Bee node.

    python3 demo/freedom/build.py && python3 demo/freedom/check.py

Two ways in, both checked against the same pack read natively in Python
(LazyOntoDAG over BeeBytesStore at the same root):

- **Freedom's path.** A stand-in for Freedom Browser's `window.swarm`
  (`readChunk`, `readSingleOwnerChunk`, `readFeedEntry`, with Freedom's
  result shapes and error reasons) is injected into the page; its calls are
  answered by Python from the node's HTTP API. The page takes it for
  Freedom and goes through `FreedomSwarm`.
- **Over HTTP** (`--url http://localhost:1633/bzz/REF/`, after
  `build.py --publish`): the page served by the node itself reads through
  `HttpSwarm` on its own origin.
- **Through a gateway** (`--gateway https://api.gateway.ethswarm.org`): the
  page served from dist/ reads every chunk from the gateway, which fetches
  from the network: the case of a browser with no Swarm of its own.

Needs a Bee node with the pack's chunks (BEE_API, default localhost:1633)
and `playwright` with Chromium.
"""

import argparse
import asyncio
import base64
import functools
import http.server
import os
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PYODIDE_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "demo", "pyodide", "node_modules", "pyodide")
API = os.environ.get("BEE_API", "http://localhost:1633").rstrip("/")
CORE = "720d44c649379c4508549200a344771a8fa29c64880744dc2372d9f57863ceb8"

FREEDOM_STANDIN = """
window.swarm = {
  isFreedomBrowser: true,
  async request({ method, params }) {
    const r = await window.__standin(method, params || {});
    if (r.error) { const e = new Error(r.error.message); e.code = r.error.code; e.data = r.error.data; throw e; }
    return r.result;
  },
  requestAccess() { return this.request({ method: 'swarm_requestAccess' }); },
  readChunk(p) { return this.request({ method: 'swarm_readChunk', params: p }); },
  readSingleOwnerChunk(p) { return this.request({ method: 'swarm_readSingleOwnerChunk', params: p }); },
  readFeedEntry(p) { return this.request({ method: 'swarm_readFeedEntry', params: p }); },
};
"""


def bee(path):
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=120) as res:
            return res.status, res.read(), res.headers
    except urllib.error.HTTPError as e:
        return e.code, b"", e.headers


def _span(raw):
    """A span as Freedom hands it over: a number, or for one past 2^53 (an
    erasure-coded chunk's level byte) a BigInt, here its decimal string,
    which BigInt() in swarm.js reads the same."""
    value = int.from_bytes(raw, "little")
    return value if value <= 2**53 - 1 else str(value)


def standin(calls, method, params):
    """Freedom's provider, answered from the node: the same results and the
    same error reasons (swarm-provider-ipc.js, chunk-service.js)."""
    calls[method] = calls.get(method, 0) + 1
    if method == "swarm_requestAccess":
        return {"result": {"connected": True}}
    if method == "swarm_readChunk":
        status, wire, _ = bee(f"/chunks/{params['reference']}")
        if status == 404:
            return {"error": {"code": -32602, "message": "Chunk not found", "data": {"reason": "chunk_not_found"}}}
        return {"result": {"data": base64.b64encode(wire[8:]).decode(), "encoding": "base64", "span": _span(wire[:8])}}
    return {"error": {"code": 4200, "message": f"{method} is not in this stand-in"}}


class _Quiet(http.server.SimpleHTTPRequestHandler):
    """dist/, with /pyodide/ answered from demo/pyodide's npm copy: the page
    is told ?pyodide=/pyodide/ instead of fetching the shared folder."""

    def log_message(self, *args):
        pass

    def translate_path(self, path):
        clean = path.split("?", 1)[0]
        if clean.startswith("/pyodide/"):
            return os.path.join(PYODIDE_DIR, clean[len("/pyodide/"):])
        return super().translate_path(path)


def serve(directory):
    handler = functools.partial(_Quiet, directory=directory)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def native(root, queries):
    """The same answers from Python, reading the same root from the node."""
    from recordstore import BeeBytesStore, RecordStore
    from ontodag.lazy import LazyOntoDAG
    dag = LazyOntoDAG(RecordStore.at(root, BeeBytesStore(API)))
    out = {}
    for name in queries["node"]:
        node = dag.nodes.get(name)
        out[("node", name)] = sorted(c.name for c in node.neighbors) if node else None
    for q in queries["get"]:
        found = sorted(i.name for i in dag.get(q.split()))
        out[("get", q)] = (len(found), found[:100])
    for a, b in queries["below"]:
        out[("below", a, b)] = dag.is_below(a, b)
    return out


async def check_page(url, root, queries, freedom, gateway=None, index=None):
    from playwright.async_api import async_playwright
    calls = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        page.on("console", lambda m: m.type == "error" and print("  page console:", m.text))
        if freedom:
            async def answer(method, params):
                # concurrent, as Freedom's provider is: each call in a thread
                return await asyncio.to_thread(standin, calls, method, params)
            await page.expose_function("__standin", answer)
            await page.add_init_script(FREEDOM_STANDIN)
        started = time.time()
        local = url.startswith("http://127.0.0.1")
        await page.goto(f"{url}?root={root}" + (f"&gateway={gateway}" if gateway else "")
                        + (f"&index={index}" if index else "") + ("&pyodide=/pyodide/" if local else ""))
        ok = await page.evaluate("window.ontodagPage.ready")
        print(f"  page ready: {ok} after {time.time() - started:.1f} s; source: {await page.inner_text('#source')}")
        if not ok:
            print("  status:", await page.inner_text("#status"))
            await browser.close()
            return None, calls
        got = {}
        for name in queries["node"]:
            t = time.time()
            a = await page.evaluate("(n) => window.ontodagPage.call('node', n)", name)
            got[("node", name)] = sorted(n for n, _c in a["below"]) if a["found"] else None
            print(f"  node {name}: {len(a['below']) if a['found'] else 'absent'} below, {a['round_trips']} round trips so far, {time.time() - t:.2f} s")
        for q in queries["get"]:
            t = time.time()
            a = await page.evaluate("(q) => window.ontodagPage.call('get', q)", q)
            got[("get", q)] = (a["count"], sorted(a["names"]))
            print(f"  get {q}: {a['count']} found, {a['records']} records read so far, {time.time() - t:.2f} s")
        for a_, b_ in queries["below"]:
            a = await page.evaluate("([a, b]) => window.ontodagPage.call('below', a, b)", [a_, b_])
            got[("below", a_, b_)] = a["below"]
        stats = await page.evaluate("window.ontodagPage.stats()")
        print(f"  chunks fetched {stats['reads']} ({stats['bytes'] // 1024} KB), reused {stats['cached']}")
        await browser.close()
    return got, calls


def compare(got, want):
    bad = 0
    for key, value in want.items():
        if got.get(key) != value:
            bad += 1
            print(f"  MISMATCH {key}: page {got.get(key)!r}, native {value!r}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=CORE)
    ap.add_argument("--url", help="the page as a node serves it (http://localhost:1633/bzz/REF/)")
    ap.add_argument("--gateway", help="read every chunk through this gateway")
    ap.add_argument("--index", help="the page's ?index= (none: walk every cone)")
    args = ap.parse_args()
    queries = {"node": ["fruit", "food", "apple", "piano-lesson", "durian-not-a-category"],
               "get": ["fruit", "berry", "fruit produce", "lesson", "physical-object", "event food"],
               "below": [("apple", "food"), ("apple", "tool"), ("piano-lesson", "teaching")]}
    want = native(args.root, queries)
    bad = 0
    if args.url:
        print(f"over HTTP: {args.url}")
        got, _ = asyncio.run(check_page(args.url, args.root, queries, freedom=False))
        bad += 1 if got is None else compare(got, want)
    elif args.gateway:
        server = serve(os.path.join(HERE, "dist"))
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        print(f"through the gateway {args.gateway}: {url}")
        got, _ = asyncio.run(check_page(url, args.root, queries, freedom=False, gateway=args.gateway))
        bad += 1 if got is None else compare(got, want)
        server.shutdown()
    else:
        server = serve(os.path.join(HERE, "dist"))
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        print(f"Freedom's path (stand-in window.swarm over {API}): {url}")
        got, calls = asyncio.run(check_page(url, args.root, queries, freedom=True, index=args.index))
        print(f"  window.swarm calls: {calls}")
        bad += 1 if got is None else compare(got, want)
        server.shutdown()
    print("all answers match the native reader" if not bad else f"{bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
