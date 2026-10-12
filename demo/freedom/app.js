// The page: Python (ontodag, recordstore) under Pyodide, Swarm through
// swarm.js. Python's synchronous store calls wait on the page's asynchronous
// Swarm reads through JSPI (pyodide.ffi.run_sync), or read by retrying where
// JSPI cannot suspend Python (pycall.js). Your own store is a local file, and
// publish.js writes it to Swarm through the node that served the page.

import { ChunkReader, BlobStore, FreedomSwarm, HttpSwarm, StoredChunks, topicOf } from "./swarm.js";
import { LocalFile, download } from "./localfile.js";
import { PythonCalls } from "./pycall.js";
import { Key, NodeWriter, Stage, feedUpdate, uploadStaged } from "./publish.js";

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

// Pyodide 0.27.7 is published once, as its own folder on Swarm, and every
// page loads it from there: it is never stamped again with a page, and a
// browser caches it under one address for every page and version. Until its
// own folder is published, the copy inside the published ontodag page.
// ?pyodide=URL names another (the checks serve a local copy).
const PYODIDE = "e0f26cbbcf0985f518fc6ffcdcad9d6ff121b1a5bd10deea6be430e83be7926a/pyodide";

function pyodideBase() {
  const named = params.get("pyodide");
  if (named) return new URL(named.endsWith("/") ? named : `${named}/`, location.href).href;
  if (location.protocol === "bzz:") return `bzz://${PYODIDE}/`;
  if (location.pathname.startsWith("/bzz/")) return `${location.origin}/bzz/${PYODIDE}/`;
  return `${params.get("gateway") || "https://api.gateway.ethswarm.org"}/bzz/${PYODIDE}/`;
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.append(s);
  });
}
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

// How Python waits for Swarm, "jspi" or "retry": pycall.js.
let calls = null;

function call(name, ...args) {
  return calls.call(name, ...args);
}

function showRetrying() {
  if (!$("source").textContent.includes("retrying")) {
    $("source").textContent += "; Python reads by retrying (it cannot wait on Swarm in this browser)";
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

// Your own store, in a file on this computer (localfile.js: saved back in
// place where the browser allows it, downloaded where it does not).
const LOCAL = "local";
const OD_TYPES = [{ description: "OntoDAG store", accept: { "text/plain": [".od"] } }];
let files = null;

function showLocal(summary, note = "") {
  $("swarmedit").classList.remove("hidden");
  if (!$("swarmname").value) $("swarmname").value = summary.name.replace(/\.od$/, "") || "store";
  const how = files.inPlace ? "Save writes back to the file" : "Save downloads the file";
  $("localstate").textContent = `${summary.name} · ${summary.count} categor${summary.count === 1 ? "y" : "ies"}` +
    (summary.changed ? " · unsaved changes" : " · saved") + ` · ${how}.` + (note ? ` ${note}` : "");
  $("localsave").disabled = false;
  $("localprelude").classList.remove("hidden");
  $("localedit").classList.remove("hidden");
  localChanged = summary.changed;
  if (![...$("store").options].some((o) => o.value === LOCAL)) {
    const o = document.createElement("option");
    o.value = LOCAL; o.textContent = "your own store";
    $("store").prepend(o);
  }
  $("store").value = LOCAL;
}

let localChanged = false;
addEventListener("beforeunload", (e) => { if (localChanged) { e.preventDefault(); e.returnValue = ""; } });

function localResult(text, warn = false) {
  $("localresult").textContent = text;
  $("localresult").classList.toggle("warn", warn);
}

async function useLocal() {
  const answer = await run("Your own store…", () => call("local_use"));
  if (answer) showNode(answer);
}

async function localNew() {
  if (localChanged && !confirm("Your store has unsaved changes. Start a new one anyway?")) return;
  files.forget();
  const summary = await call("local_new");
  showLocal(summary);
  await useLocal();
}

async function localOpen() {
  if (localChanged && !confirm("Your store has unsaved changes. Open another anyway?")) return;
  const file = await files.open();
  if (!file) return;
  const summary = await run(`Opening ${file.name}…`, async () => call("local_open", await file.text(), file.name));
  if (!summary) return;
  showLocal(summary);
  await useLocal();
}

async function localSave() {
  const { text, name } = await call("local_text");
  const where = await files.save(text, name);
  if (!where) return;
  const summary = await call("local_saved", where.name);
  showLocal(summary, where.how === "download" ? "Downloaded; keep it where you like and open it next time." : "");
}

async function localPut() {
  const item = $("putitem").value.trim();
  if (!item) return;
  const answer = await call("local_put", item, $("putunder").value.trim());
  if (answer.error) return localResult(answer.error, true);
  localResult(`put ${answer.put}${answer.under.length ? ` under ${answer.under.join(", ")}` : " at the top"}`);
  $("putitem").value = "";
  showLocal(await call("local_saved_state"));
  await goto(answer.put);
}

async function localRemove() {
  const names = $("removenames").value.trim();
  if (!names) return;
  const answer = await call("local_remove", names);
  if (answer.error) return localResult(answer.error, true);
  localResult(`removed ${answer.removed.join(", ")}`);
  $("removenames").value = "";
  showLocal(await call("local_saved_state"));
  await useLocal();
}

async function localPrelude() {
  const answer = await call("local_prelude");
  localResult(answer.added ? `added ${answer.added} declarations for typed values` : "the prelude is already here");
  showLocal(await call("local_saved_state"));
}

// Your store on Swarm (publish.js): a key the person keeps in a file, the
// node that served this page and its batches, and the store's name.
let key = null;
let writer = null;          // a NodeWriter, when the page came from a node
const stage = new Stage();
globalThis.ontodagStage = stage;

function swarmResult(text, warn = false) {
  $("swarmresult").textContent = text;
  $("swarmresult").classList.toggle("warn", warn);
}

const short = (ref) => `${ref.slice(0, 8)}…`;

function showKey(note = "") {
  $("keystate").textContent = key ? `Key ${key.checksummed}.${note ? ` ${note}` : ""}` : "No key yet: publishing needs one.";
  $("publish").disabled = !(key && writer && $("swarmbatch").value);
  $("fetch").disabled = !key;
}

function keyNew() {
  if (key && !confirm("Make a new key? What you published under the key you have stays under it; keep its file.")) return;
  key = Key.generate();
  const file = `ontodag-key-${key.address.slice(0, 6)}.txt`;
  download(key.text(), file);
  showKey(`Saved as ${file} in your downloads. Keep that file: whoever has it can change what you publish, and without it you cannot.`);
}

function keyOpen() {
  const input = $("keyfile");
  input.value = "";
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    try {
      key = Key.fromText(await file.text());
      showKey(`From ${file.name}.`);
    } catch (e) {
      swarmResult(`${file.name}: ${e.message}`, true);
    }
  };
  input.click();
}

function swarmName() {
  const name = $("swarmname").value.trim();
  if (!name || name.includes("/") || name === "..") {
    swarmResult("Give the store a name on Swarm (no slashes), as in odag -f swarm:NAME.", true);
    return null;
  }
  return name;
}

// The newest root under this name and key: through the node when the page
// has one (the update checked against the key's address), or through what
// reads Swarm here.
async function feedNow(name) {
  return writer ? writer.feedRoot(key.address, topicOf(name)) : reader.feedRoot(key.address, topicOf(name));
}

async function swarmPublish() {
  const name = swarmName();
  if (!name || !key || !writer) return;
  const batch = $("swarmbatch").value;
  const answer = await run(`Publishing ${name}…`, async () => {
    swarmResult("Reading the feed…");
    const feed = await feedNow(name);
    const answer = await call("local_publish", feed ? feed.root : "");
    if (answer.error) return answer;
    await uploadStaged(stage, writer, batch, { progress: (t) => swarmResult(`${t}…`) });
    if (feed && feed.root === answer.root) {
      answer.index = feed.index;
      answer.unchanged = true;
      return answer;
    }
    answer.index = feed ? feed.index + 1 : 0;
    swarmResult("Pointing the feed at the new root…");
    const update = feedUpdate(key, topicOf(name), answer.index, answer.root, Math.floor(Date.now() / 1000));
    await writer.writeFeed(update, batch);
    const now = await writer.feedRoot(key.address, topicOf(name));
    if (!now || now.root !== answer.root) throw new Error("the feed did not read back the new root; publish again");
    return answer;
  });
  if (!answer) return swarmResult(`Not published: ${$("status").textContent}`, true);
  if (answer.error) return swarmResult(answer.error, true);
  const merged = answer.merged
    ? ` The feed had changes made elsewhere, folded in first${answer.came_in.length ? `: ${answer.came_in.join(", ")}${answer.more ? ` and ${answer.more} more` : ""}` : ""}. Save your file to keep them.`
    : "";
  swarmResult(answer.unchanged
    ? `${name} is already published as it is: root ${answer.root} (feed update ${answer.index}).`
    : `Published ${name}: root ${answer.root}, feed update ${answer.index}, owner ${key.checksummed}.${merged}`);
  showLocal(await call("local_saved_state"));
  await useLocal();
}

async function swarmFetch() {
  const name = swarmName();
  if (!name || !key) return;
  const answer = await run(`Getting ${name} from Swarm…`, async () => {
    const feed = await feedNow(name);
    return call("local_fetch", feed ? feed.root : "");
  });
  if (!answer) return swarmResult(`Not fetched: ${$("status").textContent}`, true);
  if (answer.error) return swarmResult(answer.error, true);
  swarmResult(answer.came_in.length || answer.more
    ? `From ${name} (root ${short(answer.fetched)}): ${answer.came_in.join(", ")}${answer.more ? ` and ${answer.more} more` : ""}. Save to keep it in your file.`
    : `Nothing new in ${name} (root ${short(answer.fetched)}).`);
  showLocal(await call("local_saved_state"));
  await useLocal();
}

// Writing goes through a Bee node: the one that served this page (opened as
// http://localhost:1633/bzz/…), or one named with ?node=URL.
async function setUpWriting() {
  const named = params.get("node");
  const served = /^https?:$/.test(location.protocol) && location.pathname.startsWith("/bzz/") ? location.origin : null;
  const base = named || served;
  const via = "To publish, open this page through your own node (with Swarm Desktop: http://localhost:1633/bzz/ontodag.eth/).";
  if (!base) {
    $("swarmnote").textContent = FreedomSwarm.present()
      ? `Publishing from Freedom waits for it to accept a chunk the page signed (freedom-browser#647). ${via} Get from Swarm works here.`
      : `Publishing needs your own Bee node, which pays for it. ${via} Get from Swarm works here.`;
    return;
  }
  const node = new NodeWriter(base);
  const batches = await node.batches();
  if (batches === null) {
    $("swarmnote").textContent = `${base} is not a node with postage batches, so this page cannot publish through it. ${via}`;
    return;
  }
  if (!batches.length) {
    $("swarmnote").textContent = `The node at ${base} has no usable postage batch. Buy one in Swarm Desktop, then reload this page.`;
    return;
  }
  writer = node;
  const select = $("swarmbatch");
  select.replaceChildren(...batches.map((b) => {
    const o = document.createElement("option");
    o.value = b.id;
    o.textContent = `${b.label || short(b.id)} · ${(b.ttl / 86400).toFixed(0)} days · ${Math.round(100 * b.full)}% full`;
    return o;
  }));
  select.classList.remove("hidden");
  $("swarmnote").textContent = `Publishing goes through the node at ${base}, paid from the batch chosen. Your key signs the store's feed; the page never stores it.`;
}

async function boot() {
  const base = pyodideBase();
  await loadScript(`${base}pyodide.js`);
  py = await loadPyodide({ indexURL: base });
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
        status(`Freedom lets a site that has not connected read only so much of Swarm a minute; waiting ${ms / 1000} s. Press "Read faster (connect)" to read five times as much.`, true);
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
from js import ontodagBlobs, ontodagStage
from ontodag.browser import (RETRY, JsBytesStore, LocalStore, PageReader, RetryingPage,
                             StagedBlobs, needing, open_published)

page = None
mine = None
retry = False          # set by the page: Python cannot wait on a promise here


class Direct:
    """The same call(method, ...) shape as RetryingPage, for objects that
    answer at once: a reader over the waiting bridge, or your own store."""

    def __init__(self, target):
        self.target = target

    def call(self, method, *args):
        return getattr(self.target, method)(*args)


opened = None


def open_store(root, index_root):
    global page, opened
    opened = (root, index_root)
    index = index_root or None
    if retry:
        page = RetryingPage(lambda: PageReader(open_published(root, ontodagBlobs, bridge=RETRY, index_root=index)))
    else:
        page = Direct(PageReader(open_published(root, ontodagBlobs, index_root=index)))
    return page.call("node")

def local_new():
    global page, mine
    mine = LocalStore()
    page = Direct(mine)
    return mine.summary()

def local_open(text, name):
    global page, mine
    mine = LocalStore.from_text(text, name)
    page = Direct(mine)
    return mine.summary()

def local_use():
    global page
    page = Direct(mine)
    return page.call("node")

def local_put(item, under):
    return mine.put(item, under)

def local_remove(names):
    return mine.remove(names)

def local_prelude():
    return mine.prelude()

def local_text():
    import json
    return json.dumps({"text": mine.text(), "name": mine.name})

def local_saved(name):
    return mine.saved(name)

def local_saved_state():
    return mine.summary()

def _staged():
    # what a publish writes, staged for the page, over what it reads
    if retry:
        reader = JsBytesStore(ontodagBlobs, RETRY)
    else:
        from pyodide.ffi import run_sync
        reader = JsBytesStore(ontodagBlobs, run_sync)
    return StagedBlobs(ontodagStage, reader)

def local_publish(feed_root):
    return needing(mine.publish, feed_root, _staged())

def local_fetch(feed_root):
    return needing(mine.fetch, feed_root, _staged())

def reopen():
    """The published store open again, in the bridge mode now set."""
    import json
    if opened is None or isinstance(page, Direct) and page.target is mine:
        return json.dumps({})
    return open_store(*opened)

def node(name):
    return page.call("node", name)

def get(query):
    return page.call("get", query)

def below(a, b):
    return page.call("below", a, b)
`);
  calls = new PythonCalls(py, globalThis.ontodagBlobs, {
    onRetry: async () => { py.globals.set("retry", true); showRetrying(); await calls.call("reopen"); },
  });
  py.globals.set("retry", calls.choose(params.get("bridge")) === "retry");
  if (calls.mode === "retry") showRetrying();

  for (const [name, root] of Object.entries(PACKS)) {
    const o = document.createElement("option");
    o.value = root; o.textContent = name;
    $("store").append(o);
  }
  $("keynew").onclick = keyNew;
  $("keyopen").onclick = keyOpen;
  $("publish").onclick = swarmPublish;
  $("fetch").onclick = swarmFetch;
  $("swarmbatch").onchange = () => showKey();
  await setUpWriting();
  showKey();
  for (const id of ["store", "root", "open", "goto", "gobutton", "query", "getbutton", "belowa", "belowb", "belowbutton", "localnew", "localopen"]) {
    $(id).disabled = false;
  }
  files = new LocalFile({ input: $("localfile"), types: OD_TYPES,
    pickers: !FreedomSwarm.present(), refusedKey: "ontodag-pickers-refused" });
  globalThis.ontodagPage.files = files;
  $("store").onchange = () => ($("store").value === LOCAL ? useLocal() : openStore($("store").value));
  $("localnew").onclick = localNew;
  $("localopen").onclick = localOpen;
  $("localsave").onclick = localSave;
  $("localprelude").onclick = localPrelude;
  $("putbutton").onclick = localPut;
  $("putunder").onkeydown = (e) => { if (e.key === "Enter") localPut(); };
  $("putitem").onkeydown = (e) => { if (e.key === "Enter") localPut(); };
  $("removebutton").onclick = localRemove;
  $("removenames").onkeydown = (e) => { if (e.key === "Enter") localRemove(); };
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
  connect: () => document.getElementById("connect").click(), files: null, bridge: () => calls && calls.mode,
  owner: () => key && key.address, writing: () => Boolean(writer) };
globalThis.ontodagPage.ready = boot().then(() => true, (e) => { status(`Could not start: ${e.message || e}`, true); console.error(e); return false; });
