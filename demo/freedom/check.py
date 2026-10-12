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

Each way also checks your own store (BROWSER.md §14) through the page's
buttons: New, Put, Save (a download, compared with `ontodag.native` for the
same writes), then Open by the file input, Put, Remove and Get. Saving back
in place through File System Access needs a native dialog, so it is not
checked here; the page falls back to the download where it is refused.

Needs a Bee node with the pack's chunks (BEE_API, default localhost:1633)
and `playwright` with Chromium.
"""

import argparse
import asyncio
import base64
import functools
import http.server
import os
import re
import subprocess
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


#: What Pyodide reads to choose its JavaScript trampoline (and so no JSPI):
#: an iPhone's navigator.platform. `--iphone` reports it, so Chromium runs the
#: page as Freedom on iOS does.
IPHONE = "Object.defineProperty(Navigator.prototype, 'platform', { get: () => 'iPhone' })"


async def check_page(url, root, queries, freedom, gateway=None, index=None, mode=None, iphone=False, publish=None):
    from playwright.async_api import async_playwright
    calls = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        page.on("console", lambda m: m.type == "error" and print("  page console:", m.text))
        if iphone:
            await page.add_init_script(IPHONE)
        if freedom:
            async def answer(method, params):
                # concurrent, as Freedom's provider is: each call in a thread
                return await asyncio.to_thread(standin, calls, method, params)
            await page.expose_function("__standin", answer)
            await page.add_init_script(FREEDOM_STANDIN)
        started = time.time()
        local = url.startswith("http://127.0.0.1")
        await page.goto(f"{url}?root={root}" + (f"&gateway={gateway}" if gateway else "")
                        + (f"&index={index}" if index else "") + ("&pyodide=/pyodide/" if local else "")
                        + (f"&bridge={mode}" if mode else "")
                        + (f"&node={API}" if publish and local else ""))
        ok = await page.evaluate("window.ontodagPage.ready")
        print(f"  page ready: {ok} after {time.time() - started:.1f} s; source: {await page.inner_text('#source')}")
        print(f"  bridge: {await page.evaluate('window.ontodagPage.bridge()')}")
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
        got["local"] = await check_local(page)
        if publish:
            got["local"] += await check_publish(page, publish)
        await browser.close()
    return got, calls


async def check_local(page):
    """Your own store through the page's buttons; the problems found."""
    import tempfile
    from ontodag import OntoDAG, native
    problems = []
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    # Downloads and the file input, as in Freedom and Brave.
    await page.evaluate("window.ontodagPage.files.pickers = false")

    async def put(item, under=""):
        await page.fill("#putitem", item)
        await page.fill("#putunder", under)
        await page.click("#putbutton")
        await page.wait_for_function("(i) => document.getElementById('localresult').textContent.includes(i)", arg=item)

    await page.click("#localnew")
    await page.wait_for_selector("#localedit:not(.hidden)")
    await put("fruit")
    await put("apple", "fruit")
    async with page.expect_download() as info:
        await page.click("#localsave")
    saved = open(await (await info.value).path()).read()
    want = OntoDAG()
    want.put("fruit", [])
    want.put("apple", ["fruit"])
    if saved != native.dumps(want):
        problems.append(f"saved text differs from native.dumps: {saved!r}")
    state = await page.inner_text("#localstate")
    if "· saved" not in state:
        problems.append(f"after saving, the page says: {state!r}")

    with tempfile.NamedTemporaryFile("w", suffix=".od", delete=False) as fh:
        fh.write(saved)
    async with page.expect_file_chooser() as chooser:
        await page.click("#localopen")
    await (await chooser.value).set_files(fh.name)
    await page.wait_for_function("document.getElementById('localstate').textContent.includes('.od')")
    await put("pear", "fruit")
    await put("food")
    await put("produce", "food")
    await page.fill("#putitem", "plum")
    await page.fill("#putunder", "fruit orchard")
    await page.click("#putbutton")
    await page.wait_for_function("document.getElementById('localresult').textContent.includes('orchard')")
    await page.fill("#removenames", "pear")
    await page.click("#removebutton")
    await page.wait_for_function("document.getElementById('localresult').textContent.includes('removed')")
    answer = await page.evaluate("window.ontodagPage.call('get', 'fruit')")
    if answer.get("names") != ["apple"]:
        problems.append(f"get fruit after the edits: {answer!r}")
    state = await page.inner_text("#localstate")
    if "unsaved changes" not in state:
        problems.append(f"after edits, the page says: {state!r}")
    os.unlink(fh.name)
    print(f"  your own store: new, put, save (download), open (file input), put, remove, get: "
          f"{'ok' if not problems else problems}")
    return problems


async def _publish(page):
    """Press Publish; the root it published, or the page's complaint."""
    await page.click("#publish")
    await page.wait_for_function(
        "() => { const r = document.getElementById('swarmresult');"
        " return /^(Published|.* is already published)/.test(r.textContent) || r.classList.contains('warn'); }",
        timeout=600_000)
    text = await page.inner_text("#swarmresult")
    found = re.search(r"root ([0-9a-f]{64})", text)
    return (found.group(1) if found and not text.startswith("Not") else None), text


def _odag(home, secret, batch, *args):
    """`odag -f swarm:NAME ...` in its own home, with the page's key."""
    env = dict(os.environ, ONTODAG_HOME=home, BEE_API=API, BEE_BATCH=batch, BEE_SIGNER=secret)
    run = subprocess.run(["odag", *args], env=env, capture_output=True, text=True, timeout=600)
    if run.returncode:
        raise RuntimeError(f"odag {' '.join(args[2:])}: {run.stderr.strip()[-300:]}")
    return run.stdout


def _feed(name, owner, other_than=None, minutes=5):
    """The feed's newest root, read natively; waiting for one other than
    `other_than` (odag points its feed once the network has the commit)."""
    from recordstore import SwarmFeedPointer
    deadline = time.time() + 60 * minutes
    while True:
        root = SwarmFeedPointer(API, name, owner=owner).get()
        if root != other_than or time.time() > deadline:
            return root
        time.sleep(10)


def _native_text(root):
    from recordstore import BeeBytesStore, RecordStore
    from ontodag import native
    from ontodag.eager import EagerOntoDAG
    return native.dumps(EagerOntoDAG(RecordStore.at(root, BeeBytesStore(API))))


async def check_publish(page, batch):
    """Your own store published through the node (BROWSER.md §16), and the
    same store written by odag with the same key: the problems found.

    A throwaway key (never printed) in a key file, opened by the page; a
    store published under a fresh name; read back natively (feed and
    store); then odag, in its own home with that key, adds to it; the
    page, not told, adds too and publishes, folding odag's change in; a
    fresh odag home reads the union from the feed; and the page, starting
    a new store, gets it from Swarm."""
    import secrets
    import tempfile
    from swarmfs.signer import Signer
    problems = []
    if not await page.evaluate("window.ontodagPage.writing()"):
        return [f"the page has no node to publish through: {await page.inner_text('#swarmnote')}"]
    secret = "0x" + secrets.token_hex(32)
    owner = Signer(secret).address_hex
    name = f"check-publish-{secrets.token_hex(4)}"
    with tempfile.TemporaryDirectory() as tmp:
        keyfile = os.path.join(tmp, "key.txt")
        with open(keyfile, "w") as fh:
            fh.write(secret + "\n")

        async def put(item, under=""):
            await page.fill("#putitem", item)
            await page.fill("#putunder", under)
            await page.click("#putbutton")
            await page.wait_for_function("(i) => document.getElementById('localresult').textContent.includes(i)", arg=item)

        await page.click("#localnew")
        await page.wait_for_selector("#swarmedit:not(.hidden)")
        await put("fruit")
        await put("apple", "fruit")
        async with page.expect_file_chooser() as chooser:
            await page.click("#keyopen")
        await (await chooser.value).set_files(keyfile)
        await page.wait_for_function("document.getElementById('keystate').textContent.startsWith('Key 0x')")
        if await page.evaluate("window.ontodagPage.owner()") != owner:
            problems.append("the page read another address from the key file")
        await page.fill("#swarmname", name)
        await page.select_option("#swarmbatch", batch)

        t = time.time()
        first, said = await _publish(page)
        print(f"  publish {name}: {said[:90]}… ({time.time() - t:.0f} s)")
        if not first:
            return problems + [f"publishing failed: {said}"]
        page_text = (await page.evaluate("window.ontodagPage.call('local_text')"))["text"]
        if await asyncio.to_thread(_feed, name, owner) != first:
            problems.append("the feed, read natively, does not name the published root")
        if await asyncio.to_thread(_native_text, first) != page_text:
            problems.append("the published store, read natively, differs from the page's")

        t = time.time()
        await asyncio.to_thread(_odag, os.path.join(tmp, "laptop"), secret, batch, "-f", f"swarm:{name}", "put", "pear", "fruit")
        second = await asyncio.to_thread(_feed, name, owner, first)
        print(f"  odag put pear with the same key: feed {second[:12]}… ({time.time() - t:.0f} s)")
        if second == first:
            return problems + ["odag's change never reached the feed"]

        await put("plum", "fruit")
        t = time.time()
        third, said = await _publish(page)
        print(f"  publish again: {said[:120]}… ({time.time() - t:.0f} s)")
        if not third or "folded in" not in said or "pear" not in said:
            problems.append(f"publishing onto odag's change did not fold it in: {said}")
        if third and await asyncio.to_thread(_feed, name, owner) != third:
            problems.append("the feed does not name the folded root")

        t = time.time()
        got = (await asyncio.to_thread(_odag, os.path.join(tmp, "fresh"), secret, batch,
                                       "-f", f"swarm:{name}", "get", "fruit")).split()
        print(f"  odag in a fresh home: get fruit: {' '.join(got)} ({time.time() - t:.0f} s)")
        if sorted(got) != ["apple", "pear", "plum"]:
            problems.append(f"odag read {got} from the feed, not apple, pear and plum")

        await page.click("#localnew")
        await page.click("#fetch")
        await page.wait_for_function("document.getElementById('swarmresult').textContent.startsWith('From ')"
                                     " || document.getElementById('swarmresult').classList.contains('warn')",
                                     timeout=300_000)
        fetched = (await page.evaluate("window.ontodagPage.call('local_text')"))["text"]
        if third and fetched != await asyncio.to_thread(_native_text, third):
            problems.append(f"a new store got from Swarm differs: {await page.inner_text('#swarmresult')}")
    print(f"  publishing: page, odag with the same key, page again, fresh odag, get from Swarm: "
          f"{'ok' if not problems else problems}")
    return problems


def compare(got, want):
    bad = len(got.get("local") or [])
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
    ap.add_argument("--bridge", choices=("jspi", "retry"),
                    help="how Python waits for Swarm (default: the page decides); "
                         "retry is what Pyodide on iOS needs")
    ap.add_argument("--iphone", action="store_true",
                    help="report an iPhone's platform, as Freedom on iOS does (Pyodide then takes its "
                         "JavaScript trampoline, and the page must read by retrying)")
    ap.add_argument("--publish", action="store_true",
                    help="also publish your own store through the node and check it against odag "
                         "(writes a few chunks with BEE_BATCH or --batch)")
    ap.add_argument("--batch", default=os.environ.get("BEE_BATCH"))
    args = ap.parse_args()
    publish = None
    if args.publish:
        if not args.batch:
            sys.exit("--publish writes to Swarm: name the batch with --batch ID or BEE_BATCH")
        publish = args.batch
    queries = {"node": ["fruit", "food", "apple", "piano-lesson", "durian-not-a-category"],
               "get": ["fruit", "berry", "fruit produce", "lesson", "physical-object", "event food"],
               "below": [("apple", "food"), ("apple", "tool"), ("piano-lesson", "teaching")]}
    want = native(args.root, queries)
    bad = 0
    if args.url:
        print(f"over HTTP: {args.url}")
        got, _ = asyncio.run(check_page(args.url, args.root, queries, freedom=False, mode=args.bridge, iphone=args.iphone,
                                        publish=publish))
        bad += 1 if got is None else compare(got, want)
    elif args.gateway:
        server = serve(os.path.join(HERE, "dist"))
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        print(f"through the gateway {args.gateway}: {url}")
        got, _ = asyncio.run(check_page(url, args.root, queries, freedom=False, gateway=args.gateway, mode=args.bridge,
                                        iphone=args.iphone, publish=publish))
        bad += 1 if got is None else compare(got, want)
        server.shutdown()
    else:
        server = serve(os.path.join(HERE, "dist"))
        url = f"http://127.0.0.1:{server.server_port}/index.html"
        print(f"Freedom's path (stand-in window.swarm over {API}): {url}")
        got, calls = asyncio.run(check_page(url, args.root, queries, freedom=True, index=args.index, mode=args.bridge,
                                               iphone=args.iphone, publish=publish))
        print(f"  window.swarm calls: {calls}")
        bad += 1 if got is None else compare(got, want)
        server.shutdown()
    print("all answers match the native reader" if not bad else f"{bad} mismatches")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
