// The read-only page: Python (ontodag, recordstore) under Pyodide, Swarm
// through swarm.js. Python's synchronous store calls wait on the page's
// asynchronous Swarm reads through JSPI (pyodide.ffi.run_sync), so every
// call into Python goes through callPromising.

import { ChunkReader, BlobStore, FreedomSwarm, HttpSwarm, StoredChunks } from "./swarm.js";

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

// Their published cone summaries (demo/freedom/publish_index.py): a broad
// category's cone in one record instead of a walk. An index for another
// root is ignored by the reader. ?index=none turns them off; ?index=ROOT
// names another.
const CONE_INDEXES = {
  // core
  "720d44c649379c4508549200a344771a8fa29c64880744dc2372d9f57863ceb8":
    "1593dbb3dafca6fc2093a7e1fa848ce157125ab155bbe772395c4117cee9dd26",
  // physics
  "79ca01f0c6b6ffdf988c539a38a08eeb6c5769d4c0c59161139c216cef581bde":
    "49c5675212566f347b35126bb6fa49a99dc476ecc1e69203c1faf398334020e5",
  // mathematics
  "aeb359949749a11c18409f75563580190ef35b88d08f2086255a707c6f8ae47b":
    "688c4ce43df7a0d33394ae6fd6f3454d011572294904a5e43fb9a4fcbfdbc039",
  // chemistry
  "722e7727a9eea5cfba86519559135fdc90485595ec3e55edd440970e70db23c4":
    "5958a8fb72c6e27f26d36be954a1042e5ed7551ddddb0df3430e161922ca7b2c",
  // biology
  "749fe2555096b2f926fe7a037831e135a99b626d73fa713f63de7591add4ff5b":
    "16073edfc9b474a8fd72398ffcc94cd06e32e73abf494370c10c68e97210e386",
  // medicine
  "7f4d4d0377290cfad59a164c72308a0b57155505fd0e668c53fab78d77c0d03c":
    "6e3b3f2d24f2d7758da4700199c159a4df6f43f9a9b83411757a685d60caca6f",
  // ai
  "dabdcecb75e80afa064fdf9b293a017efcef3966e40644374b4eccb626f87c0d":
    "9413c6b8bfdcdfa339b2f1be70388799947880ad49056c287bc09acbc7bd2fc6",
  // economics
  "9471b8952711bdb05dcd3edc5168c15070ea3afa055628e71a942d3cbedd3ffd":
    "7709989c5b77ee8e40545a1367476514002db36ae8266a588439aa09c0b8d44e",
  // computing
  "05b8a5ce82a1ecde69ce478c6fc8aa3c02faf91442dcd5cfcb678ef0c9c3a43c":
    "a67407fdaa88b4cbc7dab4d590853f993046afa8348904a7a3950485fc4c9eaf",
  // geography
  "37332a36ab9e8415067396e4a80688213fe5798fe106bb0028e1444b2f9a38c7":
    "0cc44aec5f5102c5c3c97f7d49ff8411ef020ef8ddaec8ce182a2716e42d0709",
  // space
  "feaea1dfc1b923c4fc74b0372900fe5cda8983ff88bdffc52a599d59689100b0":
    "55b0a791a2d96236f4618d43638d0e5fb46038b82e3c2e7e5cfbbf3c06170b9f",
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
    `chunks fetched ${s.reads} (${kb} KB), kept from earlier visits ${s.stored}, reused ${s.cached}` +
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

function indexFor(root) {
  const named = params.get("index");
  if (named === "none") return "";
  return named || CONE_INDEXES[root] || "";
}

async function openStore(root) {
  const answer = await run("Opening the store…", () => call("open_store", root, indexFor(root)));
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
  const connected = { yes: false };
  reader = new ChunkReader(source, {
    stored: await StoredChunks.open(),
    onRateLimit: (ms) => {
      if (source instanceof FreedomSwarm && !connected.yes) {
        status(`Freedom lets a site that has not connected read only so much of Swarm a minute; waiting ${ms / 1000} s. Connect to Freedom to read five times as much.`, true);
        $("connect").classList.add("primary");
      } else {
        status(`The read budget is spent; waiting ${ms / 1000} s…`, true);
      }
    },
  });
  globalThis.ontodagBlobs = new BlobStore(reader);
  if (source instanceof FreedomSwarm) {
    $("connect").classList.remove("hidden");
    $("connect").onclick = async () => {
      try {
        await source.connect();
        connected.yes = true;
        $("connect").disabled = true;
        $("connect").classList.remove("primary");
        $("connect").textContent = "Connected";
      }
      catch (e) { status(`Freedom did not connect: ${e.message}`, true); }
    };
  }

  await py.runPythonAsync(`
from js import ontodagBlobs
from ontodag.browser import PageReader, open_published

page = None

def open_store(root, index_root):
    global page
    page = PageReader(open_published(root, ontodagBlobs, index_root=index_root or None))
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
globalThis.ontodagPage = { call, openStore, goto, stats: () => reader && reader.stats, ready: null, python: () => py,
  connect: () => document.getElementById("connect").click() };
globalThis.ontodagPage.ready = boot().then(() => true, (e) => { status(`Could not start: ${e.message || e}`, true); console.error(e); return false; });
