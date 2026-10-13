// The page: Python (ontodag, recordstore) under Pyodide, Swarm through
// swarm.js. Python's synchronous store calls wait on the page's asynchronous
// Swarm reads through JSPI (pyodide.ffi.run_sync), or read by retrying where
// JSPI cannot suspend Python (pycall.js). Your own store is a local file, and
// publish.js writes it to Swarm through the node that served the page.

import { ChunkReader, BlobStore, FreedomSwarm, HttpSwarm, StoredChunks, topicOf } from "./swarm.js";
import { LocalFile, download } from "./localfile.js";
import { SaveHelp, flagJustTurnedOn, isBrave, saveAdvice } from "./savehelp.js";
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
    if (answer && "records" in answer) showStats(answer);
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

// Your own store, organised (BROWSER.md §17): your store first, kept in a
// file on this computer (localfile.js: saved back in place where the browser
// allows it, downloaded where it does not), with the vocabularies (the
// packs, shipped beside the page as packs.json) shown beside it. Answers
// read your store and the vocabularies shown together; writes go to your
// store alone (ontodag.browser.Organiser).
const OD_TYPES = [{ description: "OntoDAG store", accept: { "text/plain": [".od"] } }];
let files = null;
let saveHelp = null;        // savehelp.js: where the browser saves only by downloading
let localChanged = false;
let hasStore = false;
let mode = "start";         // "start", "store" or "browse"
let packNames = [];         // the vocabularies, from packs.json
const shown = new Set();    // shown beside your store
// The vocabularies you turned off, remembered in this browser (core is
// shown from the start unless you did).
const OFF_KEY = "ontodag-vocabularies-off";
const untickedByYou = new Set((() => {
  try { return JSON.parse(localStorage.getItem(OFF_KEY) || "[]"); } catch { return []; }
})());
function rememberOff() {
  try { localStorage.setItem(OFF_KEY, JSON.stringify([...untickedByYou])); } catch { /* storage off */ }
}
let viewing = null;         // what the work area shows: {category}, {find}, {all} or null

addEventListener("beforeunload", (e) => { if (localChanged) { e.preventDefault(); e.returnValue = ""; } });

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "onclick") e.onclick = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined) e.append(c);
  return e;
}

// What a person typed, spelled as names are (ontodag.suggest.key).
const keyOf = (text) => text.trim().toLowerCase().split(/\s+/).filter(Boolean).join("-");

function showMode(m) {
  mode = m;
  $("start").classList.toggle("hidden", m !== "start");
  $("app").classList.toggle("hidden", m !== "store");
  $("browse").classList.toggle("hidden", m !== "browse");
  $("shownline").classList.toggle("hidden", m !== "store");
  $("browseback").textContent = hasStore ? "Back to your store" : "Back";
}

// ---- the vocabularies shown beside your store

// Core, then the packs over it, then the units and currencies.
function packsInMenu() {
  const domain = Object.keys(PACKS).filter((p) => packNames.includes(p));
  return [...domain, ...packNames.filter((p) => p !== "prelude" && !domain.includes(p)).sort()];
}

function renderVocabMenu() {
  const box = (p) => {
    const b = el("input", { type: "checkbox", "data-pack": p });
    b.checked = shown.has(p);
    b.disabled = !hasStore;
    b.onchange = () => setShown(p, b.checked, true);
    return el("label", {}, b, ` ${p}`);
  };
  const list = $("vocablist");
  list.replaceChildren();
  if (!hasStore) list.append(el("div", { class: "muted small", style: "padding:2px 8px" }, "Start a store of yours to show them beside it."));
  const units = packsInMenu().filter((p) => !(p in PACKS));
  packsInMenu().filter((p) => p in PACKS).forEach((p) => list.append(box(p)));
  if (units.length) {
    list.append(el("div", { class: "head" }, "Units and currencies"));
    units.forEach((p) => list.append(box(p)));
  }
}

function renderShownLine() {
  const on = packsInMenu().filter((p) => shown.has(p));
  const line = $("shownline");
  line.replaceChildren(el("span", {}, "Shown with your store:"));
  for (const p of on) {
    const box = el("input", { type: "checkbox" });
    box.checked = true;
    box.onchange = () => setShown(p, false, true);
    line.append(el("label", { class: "vchip" }, box, ` ${p}`));
  }
  if (!on.length) line.append(el("span", {}, "no vocabularies"));
  line.append(el("button", { class: "link", onclick: (e) => { e.stopPropagation(); toggleMenu("vocabmenu"); } }, on.length ? "change" : "add one"));
}

async function applyShown() {
  const answer = await run("Reading the vocabularies shown…", () => call("org_show", JSON.stringify([...shown])));
  renderVocabMenu();
  renderShownLine();
  return answer;
}

async function setShown(pack, on, byYou) {
  if (on) { shown.add(pack); untickedByYou.delete(pack); } else { shown.delete(pack); if (byYou) untickedByYou.add(pack); }
  rememberOff();
  await applyShown();
  await showView();
}

// The packs your store takes names from are shown, unless you turned them off.
async function showWhatYouUse() {
  const uses = (await call("org_uses")).packs.filter((p) => !shown.has(p) && !untickedByYou.has(p));
  if (!uses.length) return [];
  uses.forEach((p) => shown.add(p));
  await applyShown();
  return uses;
}

function toggleMenu(id) {
  for (const m of ["vocabmenu", "storemenu"]) if (m !== id) $(m).classList.add("hidden");
  $(id).classList.toggle("hidden");
}
document.addEventListener("click", (e) => {
  if (!e.target.closest(".menuwrap")) for (const m of ["vocabmenu", "storemenu"]) $(m).classList.add("hidden");
});

// ---- suggestions as you type (ontodag.suggest: yours first, then the
// vocabularies', each with where it sits, core's also by its WordNet words)

// Where a name sits: in your store, and in the packs that put it under
// something (a pack that only mentions it, at its top, is left out unless
// no pack places it).
function placesText(s) {
  const parts = [];
  if (s.mine) parts.push("yours");
  const placed = s.places.filter(([, parents]) => parents.length);
  for (const [pack, parents] of placed.length ? placed : s.places.slice(0, 1)) {
    parts.push(`${pack}${parents.length ? `, under ${parents.join(", ")}` : ", at its top"}`);
  }
  if (s.word) parts.push(`for “${s.word}”`);
  else if (s.also.length) parts.push(`also: ${s.also.slice(0, 4).join(", ")}`);
  return parts.join(" · ");
}

function attachSuggest(input, { lastWord = false, offerNew = "new category", onPick = null } = {}) {
  const box = el("div", { class: "suggest" });
  box.hidden = true;
  input.parentElement.append(box);
  let rows = [], hi = -1, seq = 0;
  const word = () => (lastWord ? input.value.split(/\s+/).pop() : input.value);
  const paint = () => [...box.children].forEach((d, i) => d.classList.toggle("hi", i === hi));
  const show = async () => {
    const typed = word();
    const mine = ++seq;
    if (!typed.trim() || !hasStore) { box.hidden = true; return; }
    const answer = await call("org_suggest", typed);
    if (mine !== seq) return;
    const k = keyOf(typed);
    rows = answer.suggestions;
    if (offerNew && k && !rows.some((r) => r.name === k) && !/[()]/.test(k)) rows.push({ name: k, isNew: true });
    hi = rows.findIndex((r) => r.name === k && !r.isNew);
    box.replaceChildren(...rows.map((r, i) => el("div", { "data-i": i },
      r.isNew ? el("span", { class: "nm new" }, `+ ${offerNew} “${r.name}”`) : el("span", { class: "nm" }, r.name),
      el("span", { class: "where" }, r.isNew ? "yours, at the top" : placesText(r)))));
    paint();
    box.hidden = !rows.length;
  };
  const pick = (i, completeOnly = false) => {
    const r = rows[i];
    if (!r) return;
    if (lastWord) {
      const words = input.value.split(/\s+/);
      words[words.length - 1] = r.name;
      input.value = `${words.join(" ")} `;
    } else {
      input.value = r.name;
    }
    box.hidden = true;
    input.focus();
    if (!completeOnly && onPick) onPick(r.name);
  };
  input.addEventListener("input", show);
  input.addEventListener("blur", () => setTimeout(() => { box.hidden = true; }, 150));
  input.addEventListener("keydown", (e) => {
    if (box.hidden) return;
    if (e.key === "ArrowDown") { hi = (hi + 1) % rows.length; paint(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { hi = (hi - 1 + rows.length) % rows.length; paint(); e.preventDefault(); }
    else if (e.key === "Tab" && rows.length) { pick(hi >= 0 ? hi : 0, true); e.preventDefault(); }
    else if (e.key === "Enter" && hi >= 0 && keyOf(word()) !== rows[hi].name) { pick(hi); e.preventDefault(); e.stopImmediatePropagation(); }
    else if (e.key === "Escape") { box.hidden = true; }
  });
  box.addEventListener("mousedown", (e) => {
    const d = e.target.closest("[data-i]");
    if (d) { e.preventDefault(); pick(Number(d.dataset.i)); }
  });
}

// ---- your store: its header, the side list, and the work area

function showStoreState(summary, note = "") {
  $("storebox").classList.remove("hidden");
  $("storename").textContent = summary.name;
  $("dirty").classList.toggle("hidden", !summary.changed);
  const how = files.inPlace ? "Save writes back to the file" : "Save downloads the file";
  $("storestate").textContent = `${summary.changed ? "unsaved changes" : "saved"} · ${how}.${note ? ` ${note}` : ""}`;
  $("localsave").classList.remove("hidden");
  $("localsave").classList.toggle("primary", summary.changed);
  $("storemenuwrap").classList.remove("hidden");
  $("savehelpopen").classList.toggle("hidden", !saveHelp.available);
  if (!$("swarmname").value) $("swarmname").value = summary.name.replace(/\.od$/, "") || "store";
  localChanged = summary.changed;
}

const chip = (name, src, extra = null) => el("button", {
  class: `chip ${src === "mine" ? "mine" : "vocab"}`, onclick: () => showCategory(name),
}, name, src && src !== "mine" && src !== "view" ? el("span", { class: "src" }, src) : null, extra);

async function refreshTree() {
  const answer = await call("org_tree");
  const on = viewing && viewing.category;
  $("tree").replaceChildren(
    el("li", {}, el("button", { class: viewing && viewing.all ? "on" : "", onclick: showAll },
      el("span", {}, "Everything in your store"), el("span", { class: "n" }, String(answer.count)))),
    ...answer.tree.map(([name, depth, below]) => el("li", { style: `padding-left:${depth * 14}px` },
      el("button", { class: name === on ? "on" : "", onclick: () => showCategory(name) },
        el("span", {}, name), el("span", { class: "n" }, below ? String(below) : "")))));
  $("treeempty").classList.toggle("hidden", answer.count > 0);
  return answer;
}

async function afterChange(note = "") {
  showStoreState(await call("local_saved_state"), note);
  await refreshTree();
}

function welcome(count) {
  return el("div", { class: "panel" },
    el("div", { class: "heading" }, el("h2", {}, count ? "Your store" : "Your store is empty")),
    el("p", { class: "muted" }, count
      ? "Pick a category on the left, or Find what is below all of some names."
      : "Add your first things: type a name, then what it is under. As you type, the vocabularies suggest names and show where each sits; anything you type that no vocabulary has becomes a category of your own."));
}

async function showView() {
  if (!viewing) {
    const tree = await refreshTree();
    $("view").replaceChildren(welcome(tree.count));
    return;
  }
  if (viewing.category) return showCategory(viewing.category);
  if (viewing.find) return showFind(viewing.find);
  if (viewing.all) return showAll();
}

async function showCategory(name) {
  viewing = { category: name };
  const n = await call("org_node", name);
  await refreshTree();
  const where = [];
  if (n.mine) where.push("yours");
  for (const [pack, parents] of n.places) {
    if (n.shown.includes(pack)) where.push(`${pack}${parents.length ? `, under ${parents.join(", ")}` : ", at its top"}`);
  }
  const panel = el("div", { class: "panel" },
    el("div", { class: "heading" }, el("h2", {}, name), el("span", { class: "muted small" }, where.join(" · ") || (n.found ? "" : "not in your store or the vocabularies shown"))));
  for (const [pack, parents] of n.places) {
    if (n.shown.includes(pack) || pack === "prelude") continue;
    panel.append(el("p", { class: "small muted" },
      `${pack} is not shown, so its places for ${name} are hidden (${pack} puts it under ${parents.join(", ") || "nothing"}). `,
      el("button", { class: "link", onclick: () => setShown(pack, true, false) }, `Show ${pack}`)));
  }
  if (n.found) {
    const above = el("div", { class: "rel" }, el("span", { class: "lbl" }, "Above"));
    if (n.above.length) n.above.forEach(([p, src]) => above.append(chip(p, src)));
    else above.append(el("span", { class: "muted" }, "nothing: it is at the top"));
    const below = el("div", { class: "rel" }, el("span", { class: "lbl" }, "Below"));
    const yours = n.below.filter(([, , src]) => src === "mine");
    const theirs = n.below.filter(([, , src]) => src !== "mine");
    yours.forEach(([c, , src]) => below.append(chip(c, src)));
    if (theirs.length) {
      const more = el("button", { class: "link" }, `${theirs.length + n.more} more from ${[...new Set(theirs.map(([, , s]) => s))].join(" and ")}`);
      more.onclick = () => { more.replaceWith(...theirs.map(([c, , src]) => chip(c, src))); if (n.more) below.append(el("span", { class: "muted small" }, `and ${n.more} more`)); };
      below.append(more);
    }
    if (!n.below.length) below.append(el("span", { class: "muted" }, "nothing"));
    panel.append(above, below);
    if (n.about.length) {
      const about = el("div", { class: "rel" }, el("span", { class: "lbl" }, "About"));
      n.about.forEach(([c, classes]) => about.append(chip(c, "mine", classes.length ? el("span", { class: "src" }, classes.join(", ")) : null)));
      panel.append(about);
    }
  }
  const put = el("input", { type: "text", id: "putunder", placeholder: `put ${name} under…, e.g. holiday`, autocomplete: "off" });
  const putField = el("div", { class: "field", style: "flex:1 1 220px" }, put);
  const doPut = async () => {
    const under = put.value.trim();
    if (!under) return;
    const a = await call("org_add", name, under);
    if (a.error) return status(a.error, true);
    await added(a);
    await showCategory(name);
  };
  const actions = el("div", { class: "bar", style: "margin-top:12px" }, putField, el("button", { onclick: doPut }, "Put"));
  if (n.mine) {
    actions.append(el("button", { class: "link", id: "removebutton", onclick: async () => {
      if (!confirm(`Remove ${name} from your store? What is below it moves up to what is above it.`)) return;
      const a = await call("org_remove", name);
      if (a.error) return status(a.error, true);
      status(`Removed ${a.removed.join(", ")}`);
      viewing = null;
      await afterChange();
      await showView();
    } }, "Remove from your store"));
  }
  panel.append(actions);
  $("view").replaceChildren(panel);
  attachSuggest(put, { lastWord: true });
  put.addEventListener("keydown", (e) => { if (e.key === "Enter") doPut(); });
}

async function showFind(query) {
  viewing = { find: query };
  $("find").value = query;
  const a = await run(`Finding ${query}…`, () => call("org_get", query));
  await refreshTree();
  if (!a) return;
  const panel = el("div", { class: "panel" }, el("div", { class: "heading" }, el("h2", {}, `Below all of: ${query}`),
    el("span", { class: "muted small" }, a.error ? "" : `${a.count} found`)));
  if (a.error) panel.append(el("p", { class: "warn" }, a.error));
  else {
    const yours = el("div", { class: "rel" }, el("span", { class: "lbl" }, "Yours"));
    a.mine.forEach((n) => yours.append(chip(n, "mine")));
    if (!a.mine.length) yours.append(el("span", { class: "muted" }, "none"));
    panel.append(yours);
    if (a.others.length) {
      const others = el("div", { class: "rel" }, el("span", { class: "lbl" }, "Shown"));
      a.others.forEach((n) => others.append(chip(n, "view")));
      if (a.more) others.append(el("span", { class: "muted small" }, `and ${a.more} more`));
      panel.append(others);
    }
  }
  $("view").replaceChildren(panel);
}

async function showAll() {
  viewing = { all: true };
  const a = await call("org_names");
  await refreshTree();
  const rel = el("div", { class: "rel" });
  a.names.forEach((n) => rel.append(chip(n, "mine")));
  if (!a.names.length) rel.append(el("span", { class: "muted" }, "nothing yet"));
  $("view").replaceChildren(el("div", { class: "panel" }, el("div", { class: "heading" }, el("h2", {}, "Everything in your store"),
    el("span", { class: "muted small" }, `${a.names.length} names`)), rel));
}

// What an add did, said plainly; the packs it took names from are shown.
async function added(a) {
  const parts = [`Added ${a.put}${a.under.length ? ` under ${a.under.join(", ")}` : " at the top"}.`];
  if (a.taken.length) parts.push(`Took ${a.taken.join(", ")} from the vocabularies, as name${a.taken.length > 1 ? "s" : ""} only.`);
  if (a.created.length) parts.push(`New categor${a.created.length > 1 ? "ies" : "y"} of yours: ${a.created.join(", ")}.`);
  if (a.prelude) parts.push("Added the declarations typed values need (the prelude).");
  const now = await showWhatYouUse();
  if (now.length) parts.push(`${now.join(" and ")} ${now.length > 1 ? "are" : "is"} now shown beside your store, since it uses ${now.length > 1 ? "their" : "its"} names.`);
  $("addresult").textContent = parts.join(" ");
  $("addresult").classList.remove("warn");
  await afterChange();
}

async function addThing() {
  const what = $("addwhat").value.trim();
  if (!what) return;
  const a = await call("org_add", what, $("addunder").value.trim());
  if (a.error) {
    $("addresult").textContent = a.error;
    $("addresult").classList.add("warn");
    return;
  }
  await added(a);
  $("addwhat").value = "";
  $("addwhat").focus();
  await showCategory(a.under[0] || a.put);
}

// ---- opening, starting and saving

async function storeOpened(note = "") {
  hasStore = true;
  showMode("store");
  if (!untickedByYou.has("core")) shown.add("core");
  await applyShown();
  const now = await showWhatYouUse();
  renderShownLine();
  await afterChange(now.length ? `${now.join(" and ")} shown beside it, since it uses ${now.length > 1 ? "their" : "its"} names.${note ? ` ${note}` : ""}` : note);
  viewing = null;
  await showView();
  await run("Reading the vocabularies shown…", () => call("org_view"));
  if (!(await call("org_tree")).count) {
    $("addpanel").classList.remove("hidden");
    $("addwhat").focus();
  }
}

async function localNew() {
  if (localChanged && !confirm("Your store has unsaved changes. Start a new one anyway?")) return;
  files.forget();
  await call("local_new");
  await storeOpened();
}

async function localOpen() {
  if (localChanged && !confirm("Your store has unsaved changes. Open another anyway?")) return;
  const file = await files.open();
  if (!file) return;
  const summary = await run(`Opening ${file.name}…`, async () => call("local_open", await file.text(), file.name));
  if (!summary) return;
  await storeOpened();
}

async function localSave() {
  const { text, name } = await call("local_text");
  const where = await files.save(text, name);
  if (!where) return;
  await call("local_saved", where.name);
  showStoreState(await call("local_saved_state"), where.how === "download" ? "Downloaded; keep it where you like and open it next time." : "");
  if (where.how === "download") saveHelp.offer();
}

// ---- browsing a published store on Swarm, read only

async function browse(root, name) {
  for (const m of ["vocabmenu", "storemenu"]) $(m).classList.add("hidden");
  showMode("browse");
  $("browsename").textContent = name;
  await openStore(root);
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
  showKey(`Saved as ${file}, in your downloads unless your browser asked where. Keep that file: whoever has it can change what you publish, and without it you cannot.`);
  saveHelp.offer();
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
  await call("org_changed");
  await afterChange();
  await showView();
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
  await call("org_changed");
  await afterChange();
  await showView();
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

# Your store, organised (ontodag.browser.Organiser): the vocabularies'
# canonical texts come from packs.json, read once.
import json as _json
from ontodag.browser import Organiser
from ontodag.suggest import Vocabularies

org = None
pack_texts = {}
vocab = None

def org_setup(packs_json):
    global pack_texts
    pack_texts = _json.loads(packs_json)["packs"]
    return _json.dumps({"packs": sorted(pack_texts)})

def org_warm():
    """Read every vocabulary's names once, and compose core, so the first
    suggestion and the first answer are quick."""
    global vocab
    if vocab is None:
        vocab = Vocabularies(pack_texts)
    o = _org()
    shown = list(o.shown)
    o.show(["core"])
    o._union()
    o.show(shown)
    return _json.dumps({"names": len(vocab.names)})

def _org():
    global org
    if org is None:
        org = Organiser(mine if mine is not None else LocalStore(), pack_texts)
        org._vocab = vocab
    elif mine is not None and org.mine is not mine:
        org.use(mine)
    return org

def org_view():
    """The composed view, built now rather than at the first answer."""
    return _json.dumps({"names": len(_org().view().nodes) - 1})

def org_show(names_json):
    return _org().show(_json.loads(names_json))

def org_uses():
    return _org().uses()

def org_tree():
    return _org().tree()

def org_node(name):
    return _org().node(name)

def org_get(query):
    return _org().get(query)

def org_suggest(text):
    return _org().suggest(text)

def org_add(item, under):
    return _org().add(item, under)

def org_remove(names):
    return _org().remove(names)

def org_names():
    return _json.dumps({"names": sorted(_org()._names(), key=lambda n: (n.lower(), n))})

def org_changed():
    """Your store changed under the page (a publish folded, a fetch came in)."""
    _org().use(mine)
    return _json.dumps({})
`);
  calls = new PythonCalls(py, globalThis.ontodagBlobs, {
    onRetry: async () => { py.globals.set("retry", true); showRetrying(); await calls.call("reopen"); },
  });
  py.globals.set("retry", calls.choose(params.get("bridge")) === "retry");
  if (calls.mode === "retry") showRetrying();

  packNames = (await call("org_setup", await (await fetch("packs.json")).text())).packs;
  for (const [name, root] of Object.entries(PACKS)) {
    $("browselist").append(el("button", { onclick: () => browse(root, name) }, name));
  }
  renderVocabMenu();
  $("vocabbtn").disabled = false;
  $("vocabbtn").onclick = (e) => { e.stopPropagation(); toggleMenu("vocabmenu"); };
  $("storemenubtn").onclick = (e) => { e.stopPropagation(); toggleMenu("storemenu"); };
  $("keynew").onclick = keyNew;
  $("keyopen").onclick = keyOpen;
  $("publish").onclick = swarmPublish;
  $("fetch").onclick = swarmFetch;
  $("swarmbatch").onchange = () => showKey();
  await setUpWriting();
  showKey();
  files = new LocalFile({ input: $("localfile"), types: OD_TYPES,
    pickers: !FreedomSwarm.present(), refusedKey: "ontodag-pickers-refused" });
  globalThis.ontodagPage.files = files;
  const brave = await isBrave();
  saveHelp = new SaveHelp({ dialog: $("savehelp"),
    advise: () => saveAdvice({ pickers: files.pickers, brave, freedom: FreedomSwarm.present() }) });
  globalThis.ontodagPage.saveHelp = saveHelp;
  $("savehelpopen").onclick = () => saveHelp.open();
  const flagOn = flagJustTurnedOn({ brave, pickers: files.pickers });

  $("startnew").onclick = localNew;
  $("startopen").onclick = localOpen;
  $("menunew").onclick = () => { toggleMenu("storemenu"); localNew(); };
  $("menuopen").onclick = () => { toggleMenu("storemenu"); localOpen(); };
  $("menupublish").onclick = () => { toggleMenu("storemenu"); $("pubpanel").classList.remove("hidden"); $("pubpanel").scrollIntoView({ block: "nearest" }); };
  $("pubclose").onclick = () => $("pubpanel").classList.add("hidden");
  $("localsave").onclick = localSave;
  $("addtoggle").onclick = () => { $("addpanel").classList.toggle("hidden"); if (!$("addpanel").classList.contains("hidden")) $("addwhat").focus(); };
  $("addbutton").onclick = addThing;
  // Suggestions first: an Enter that picks one goes no further.
  attachSuggest($("addwhat"), { offerNew: "new name" });
  attachSuggest($("addunder"), { lastWord: true });
  attachSuggest($("find"), { lastWord: true, offerNew: null });
  $("addwhat").addEventListener("keydown", (e) => { if (e.key === "Enter") $("addunder").focus(); });
  $("addunder").addEventListener("keydown", (e) => { if (e.key === "Enter") addThing(); });
  const find = () => { const q = $("find").value.trim(); if (q) showFind(q); };
  $("findbutton").onclick = find;
  $("find").addEventListener("keydown", (e) => { if (e.key === "Enter") find(); });
  $("browseback").onclick = () => { showMode(hasStore ? "store" : "start"); history.replaceState(null, "", location.pathname + location.search); };

  $("open").onclick = () => {
    const root = $("root").value.trim().toLowerCase();
    if (/^[0-9a-f]{64}$/.test(root)) browse(root, `${root.slice(0, 8)}…`);
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

  // A link may name a published store (?root= or ?pack=) to browse; otherwise
  // the page starts with your store.
  const named = params.get("root") || (params.get("pack") && PACKS[params.get("pack")]);
  if (named) await browse(named, params.get("pack") || `${named.slice(0, 8)}…`);
  else showMode("start");
  status("Preparing the vocabularies (a few seconds)…");
  await call("org_warm");
  status(flagOn ? "Brave's flag is on: Save now writes back to the file you opened." : "Ready.");
}

// For tests and the console: the page's own calls.
globalThis.ontodagPage = { call, openStore, goto, stats: () => reader && reader.stats, ready: null, python: () => py,
  connect: () => document.getElementById("connect").click(), files: null, bridge: () => calls && calls.mode,
  owner: () => key && key.address, writing: () => Boolean(writer), showCategory, showFind,
  shown: () => [...shown], mode: () => mode };
globalThis.ontodagPage.ready = boot().then(() => true, (e) => { status(`Could not start: ${e.message || e}`, true); console.error(e); return false; });
