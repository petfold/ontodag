// A file on the person's computer that a page opens and saves (BROWSER.md
// §14). Where the browser lets a page keep a file it was given (File System
// Access), save writes back to that file. Chrome asks before an opened file
// is written. Freedom (from 0.8.8) grants read on an opened file and write
// only on one picked in the save dialog (Electron's check can say yes or
// no, never ask), so saving back to an opened file asks once with the save
// dialog, named after that file. Freedom before 0.8.8 refuses even reading
// after the pick, and Brave has no pickers: there a file input opens and a
// download saves. A refusal is remembered (per origin), so the pickers are
// not offered again.
//
// loopmarket's page copies this file in (its build.py), as it does swarm.js.

export class LocalFile {
  // input: a hidden <input type="file">; types: the pickers' file types;
  // pickers: false to skip them up front (in Freedom, say);
  // refusedKey: where a refusal is remembered; downloadType: what a
  // download is typed as (a type the file's extension does not stand for
  // makes Android add one: store.od saved as store.od.txt).
  constructor({ input, types, pickers = true, refusedKey = "local-file-pickers-refused", downloadType = "text/plain" }) {
    this.input = input;
    this.types = types;
    this.downloadType = downloadType;
    this.refusedKey = refusedKey;
    this.handle = null;
    this.fromSaveDialog = false;
    this.pickers = pickers && typeof showOpenFilePicker === "function" && !this._refused();
  }

  // Save writes back to the file that was opened (rather than downloading).
  get inPlace() { return Boolean(this.handle); }

  forget() { this.handle = null; this.fromSaveDialog = false; }

  _refused() {
    try { return localStorage.getItem(this.refusedKey) === "1"; } catch { return false; }
  }

  _refuse(e) {
    console.warn("file pickers refused; opening and saving by file input and download instead", e);
    this.pickers = false;
    this.handle = null;
    try { localStorage.setItem(this.refusedKey, "1"); } catch { /* storage off */ }
  }

  _byInput() {
    return new Promise((resolve) => {
      this.input.value = "";
      this.input.onchange = () => resolve(this.input.files[0] || null);
      this.input.click();
    });
  }

  // The File chosen, or null if the person cancelled.
  async open() {
    if (this.pickers) {
      try {
        const [handle] = await showOpenFilePicker({ types: this.types });
        const file = await handle.getFile();
        this.handle = handle;
        this.fromSaveDialog = false;
        return file;
      } catch (e) {
        if (e.name === "AbortError") return null;
        this._refuse(e);
      }
    }
    this.handle = null;
    return this._byInput();
  }

  // Where the text went: { how: "file" | "download", name }, or null if the
  // person cancelled.
  async save(text, name) {
    if (this.pickers) {
      try {
        if (!this.handle) await this._askWhere(name);
        let w;
        try {
          w = await this._writable(this.handle);
        } catch (e) {
          if (e.name !== "NotAllowedError" || this.fromSaveDialog) throw e;
          await this._askWhere(this.handle.name);   // an opened file may only be read
          w = await this._writable(this.handle);
        }
        await w.write(text);
        await w.close();
        return { how: "file", name: this.handle.name };
      } catch (e) {
        if (e.name === "AbortError") return null;
        this._refuse(e);
      }
    }
    download(text, name, this.downloadType);
    return { how: "download", name };
  }

  async _askWhere(name) {
    this.handle = await showSaveFilePicker({ suggestedName: name, types: this.types });
    this.fromSaveDialog = true;
  }

  async _writable(handle) {
    const mode = { mode: "readwrite" };
    if (await handle.queryPermission(mode) !== "granted"
        && await handle.requestPermission(mode) !== "granted") {
      throw new DOMException("write permission not granted", "NotAllowedError");
    }
    return handle.createWritable();
  }
}

export function download(text, name, type = "text/plain") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}
