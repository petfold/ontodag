// node demo/freedom/test/test_localfile.mjs
// Checks localfile.js against browsers that grant File System Access the way
// Chrome does and the way Freedom does (#671): Freedom grants read on a file
// the person opened and read and write on one they picked in the save
// dialog, and refuses to upgrade an opened file to write (Electron's check
// can only say yes or no, never ask). Saving back to an opened file then
// asks once with the save picker, named after that file, before it gives up
// on pickers and downloads.
const kept = new Map();
globalThis.localStorage = {
  getItem: (k) => (kept.has(k) ? kept.get(k) : null),
  setItem: (k, v) => kept.set(k, String(v)),
  removeItem: (k) => kept.delete(k),
};
const downloads = [];
globalThis.document = {
  createElement: () => ({ click() { downloads.push(this.download); }, remove() {} }),
  body: { append() {} },
};
globalThis.URL.createObjectURL = () => "blob:test";
globalThis.URL.revokeObjectURL = () => {};
globalThis.setTimeout = () => 0;

const refused = (what) => new DOMException(what, "NotAllowedError");

// A file handle: `writes` says whether the browser lets the page write it.
class Handle {
  constructor(name, { writes }) { this.name = name; this.writes = writes; this.text = "old"; }
  async getFile() { return { name: this.name, text: async () => this.text }; }
  async queryPermission() { return this.writes ? "granted" : "prompt"; }
  async requestPermission() { return this.writes ? "granted" : "denied"; }
  async createWritable() {
    if (!this.writes) throw refused("write refused");
    const h = this;
    return { write: async (t) => { h.text = t; }, close: async () => {} };
  }
}

// The browser's pickers, set per case: what the open and the save dialog hand over.
let opens, saves;
globalThis.showOpenFilePicker = async () => [opens()];
globalThis.showSaveFilePicker = async (options) => saves(options);

const { LocalFile } = await import("../localfile.js");
let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failures++; };
const fresh = () => { kept.clear(); downloads.length = 0; return new LocalFile({ input: null, types: [] }); };

{ // Chrome: an opened file is written back in place.
  const file = fresh();
  const opened = new Handle("store.od", { writes: true });
  opens = () => opened;
  saves = () => { throw new Error("no save dialog expected"); };
  await file.open();
  const where = await file.save("new", "store.od");
  check(where.how === "file" && opened.text === "new", "Chrome: an opened file is saved back in place");
}

{ // Freedom: writing an opened file is refused, so the save dialog asks once,
  // named after that file; later saves write without a dialog.
  const file = fresh();
  const opened = new Handle("store.od", { writes: false });
  const picked = new Handle("store.od", { writes: true });
  let asked = 0, suggested = null;
  opens = () => opened;
  saves = (options) => { asked++; suggested = options.suggestedName; return picked; };
  await file.open();
  const first = await file.save("one", "other-name.od");
  const second = await file.save("two", "other-name.od");
  check(first.how === "file" && suggested === "store.od" && picked.text === "two" && asked === 1 && file.pickers,
        "Freedom: saving an opened file asks once with the save dialog, named after it, then saves in place");
}

{ // Cancelling that save dialog is a cancel, not a refusal of the pickers.
  const file = fresh();
  opens = () => new Handle("store.od", { writes: false });
  saves = () => { throw new DOMException("cancelled", "AbortError"); };
  await file.open();
  const where = await file.save("x", "store.od");
  check(where === null && file.pickers && downloads.length === 0, "a cancelled save dialog cancels the save and keeps the pickers");
}

{ // Refused in the save dialog too: the pickers are given up and the store downloads.
  const file = fresh();
  opens = () => new Handle("store.od", { writes: false });
  saves = () => new Handle("store.od", { writes: false });
  await file.open();
  const where = await file.save("x", "store.od");
  check(where.how === "download" && !file.pickers && downloads[0] === "store.od",
        "refused in the save dialog too: download, and the pickers are given up");
}

{ // A browser that refuses even reading what was opened (Freedom before 0.8.8)
  // falls back to the file input at once.
  const file = fresh();
  const old = new Handle("store.od", { writes: false });
  old.getFile = async () => { throw refused("read refused"); };
  opens = () => old;
  file.input = { click() { queueMicrotask(() => this.onchange()); }, files: [{ name: "store.od" }], value: "" };
  const got = await file.open();
  check(got && got.name === "store.od" && !file.pickers, "reading refused after the open dialog: the file input instead");
}

if (failures) { console.log(`${failures} failed`); process.exit(1); }
console.log("all passed");
