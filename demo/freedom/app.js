// The read-only page: Python (ontodag, recordstore) under Pyodide, Swarm
// through swarm.js. Python's synchronous store calls wait on the page's
// asynchronous Swarm reads through JSPI (pyodide.ffi.run_sync), so every
// call into Python goes through callPromising.

import { ChunkReader, BlobStore, FreedomSwarm, HttpSwarm } from "./swarm.js";

// The published packs, by the roots ontodag pins for them (tests/test_packs.py
// SWARM_GOLDEN_ROOTS): equal knowledge, equal root, so a root is the whole
// identity of what is read.
const PACKS = {
  core: "720d44c649379c4508549200a344771a8fa29c64880744dc2372d9f57863ceb8",
  physics: "79ca01f0c6b6ffdf988c539a38a08eeb6c5769d4c0c59161139c216cef581bde",
  mathematics: "aeb359949749a11c18409f75563580190ef35b88d08f2086255a707c6f8ae47b",
  chemistry: "722e7727a9eea5cfba86519559135fdc90485595ec3e55edd440970e70db23c4",
  biology: "749fe2555096b2f926fe7a037831e135a99b626d73fa713f63de7591add4ff5b",
  medicine: "7f4d4d0377290cfad59a164c72308a0b57155505fd0e668c53fab78d77c0d03c",
  ai: "dabdcecb75e80afa064fdf9b293a017efcef3966e40644374b4eccb626f87c0d",
  economics: "9471b8952711bdb05dcd3edc5168c15070ea3afa055628e71a942d3cbedd3ffd",
  computing: "05b8a5ce82a1ecde69ce478c6fc8aa3c02faf91442dcd5cfcb678ef0c9c3a43c",
  geography: "37332a36ab9e8415067396e4a80688213fe5798fe106bb0028e1444b2f9a38c7",
  space: "feaea1dfc1b923c4fc74b0372900fe5cda8983ff88bdffc52a599d59689100b0",
};

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
let py, reader, page;
let busy = false;

function status(text, warn = false) {
  $("status").textContent = text;
  $("status").classList.toggle("warn", warn);
}

// Outside Freedom: the node that served this page (a /bzz/ URL), or a
// gateway named in ?gateway=, or the public gateway.
function chooseSource() {
  if (FreedomSwarm.present()) return new FreedomSwarm();
  const named = params.get("gateway");
  if (named) return new HttpSwarm(named);
  if (location.pathname.startsWith("/bzz/")) return new HttpSwarm(location.origin);
  return new HttpSwarm("https://api.gateway.ethswarm.org");
}

function showStats(answer) {
  const s = reader.stats;
  const kb = (s.bytes / 1024).toFixed(0);
  $("stats").textContent =
    `records read ${answer.records} in ${answer.round_trips} round trips · ` +
    `chunks fetched ${s.reads} (${kb} KB), reused ${s.cached}` +
    (s.waits ? ` · waited for the read budget ${s.waits}×` : "");
}

async function call(name, ...args) {
  // Python's store calls block on swarm.js's promises (run_sync), which
  // works only for a call that entered Python asynchronously.
  const fn = py.globals.get(name);
  try {
    return JSON.parse(await fn.callPromising(...args));
  } finally {
    fn.destroy();
  }
}

async function run(what, action) {
  if (busy) return;
  busy = true;
  const started = performance.now();
  status(what);
  try {
    const answer = await action();
    status(`${what.replace(/…$/, "")}: ${((performance.now() - started) / 1000).toFixed(1)} s`);
    showStats(answer);
    return answer;
  } catch (e) {
    status(`${e.message || e}`, true);
    console.error(e);
  } finally {
    busy = false;
  }
}

function link(name, onClick) {
  const a = document.createElement("a");
  a.textContent = name;
  a.onclick = (e) => { e.preventDefault(); onClick(name); };
  return a;
}

function showNode(answer) {
  if (!answer.found) {
    status(`${answer.name} is not in this store`, true);
    return;
  }
  $("nodename").textContent = answer.top ? "the top of the store" : answer.name;
  $("nodecount").textContent = `${answer.count} below`;
  $("above").replaceChildren(...answer.above.map((n) => {
    const li = document.createElement("li"); li.append(link(n, goto)); return li;
  }));
  $("below").replaceChildren(...answer.below.map(([n, c]) => {
    const li = document.createElement("li");
    li.append(link(n, goto));
    if (c) li.append(` ${c}`);
    return li;
  }));
  if (answer.more) {
    const li = document.createElement("li");
    li.textContent = `and ${answer.more} more`;
    $("below").append(li);
  }
  if (!answer.top) history.replaceState(null, "", `#${encodeURIComponent(answer.name)}`);
}

async function goto(name) {
  const answer = await run(`Reading ${name}…`, () => call("node", name));
  if (answer) showNode(answer);
}

async function openStore(root) {
  const answer = await run("Opening the store…", () => call("open_store", root));
  if (!answer) return;
  showNode(answer);
  const start = decodeURIComponent(location.hash.slice(1));
  if (start) await goto(start);
}

async function boot() {
  py = await loadPyodide({ indexURL: new URL("pyodide/", location.href).href });
  status("Installing ontodag…");
  const manifest = await (await fetch("wheels/manifest.json")).json();
  await py.loadPackage(manifest.wheels.map((w) => new URL(`wheels/${w}`, location.href).href));

  const source = chooseSource();
  $("source").textContent = `Reading Swarm through ${source.kind}`;
  reader = new ChunkReader(source, {
    onRateLimit: (ms) => status(`The browser's read budget is spent; waiting ${ms / 1000} s…`, true),
  });
  globalThis.ontodagBlobs = new BlobStore(reader);
  if (source instanceof FreedomSwarm) {
    $("connect").classList.remove("hidden");
    $("connect").onclick = async () => {
      try { await source.connect(); $("connect").disabled = true; $("connect").textContent = "Connected"; }
      catch (e) { status(`Freedom did not connect: ${e.message}`, true); }
    };
  }

  await py.runPythonAsync(`
from js import ontodagBlobs
from ontodag.browser import PageReader, open_published

page = None

def open_store(root):
    global page
    page = PageReader(open_published(root, ontodagBlobs))
    return page.node()

def node(name):
    return page.node(name)

def get(query):
    return page.get(query)

def below(a, b):
    return page.below(a, b)
`);

  for (const [name, root] of Object.entries(PACKS)) {
    const o = document.createElement("option");
    o.value = root; o.textContent = name;
    $("store").append(o);
  }
  for (const id of ["store", "root", "open", "goto", "gobutton", "query", "getbutton", "belowa", "belowb", "belowbutton"]) {
    $(id).disabled = false;
  }
  $("store").onchange = () => openStore($("store").value);
  $("open").onclick = () => {
    const root = $("root").value.trim().toLowerCase();
    if (/^[0-9a-f]{64}$/.test(root)) openStore(root);
    else status("A root is 64 hex digits", true);
  };
  $("gobutton").onclick = () => $("goto").value.trim() && goto($("goto").value.trim());
  $("goto").onkeydown = (e) => { if (e.key === "Enter") $("gobutton").click(); };
  $("getbutton").onclick = async () => {
    const q = $("query").value.trim();
    if (!q) return;
    const answer = await run(`get ${q}…`, () => call("get", q));
    if (!answer) return;
    const box = $("getresult");
    if (answer.error) { box.textContent = answer.error; return; }
    box.replaceChildren(document.createTextNode(`${answer.count} found${answer.count ? ": " : ""}`));
    answer.names.forEach((n, i) => { if (i) box.append(", "); box.append(link(n, goto)); });
    if (answer.more) box.append(` and ${answer.more} more`);
  };
  $("query").onkeydown = (e) => { if (e.key === "Enter") $("getbutton").click(); };
  $("belowbutton").onclick = async () => {
    const a = $("belowa").value.trim(), b = $("belowb").value.trim();
    if (!a || !b) return;
    const answer = await run(`Is ${a} below ${b}?…`, () => call("below", a, b));
    if (answer) $("belowresult").textContent = answer.error || `${a} is ${answer.below ? "" : "not "}below ${b}`;
  };

  const chosen = params.get("root") || PACKS[params.get("pack") || "core"] || PACKS.core;
  $("store").value = chosen;
  await openStore(chosen);
}

// For tests and the console: the page's own calls.
globalThis.ontodagPage = { call, openStore, goto, stats: () => reader && reader.stats, ready: null };
globalThis.ontodagPage.ready = boot().then(() => true, (e) => { status(`Could not start: ${e.message || e}`, true); console.error(e); return false; });
