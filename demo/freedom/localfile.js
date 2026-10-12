// A file on the person's computer that a page opens and saves (BROWSER.md
// §14). Where the browser lets a page keep a file it was given (File System
// Access, in Chrome), save writes back to that file. Freedom refuses that
// access after the pick and Brave has no pickers, so there a file input
// opens and a download saves. A refusal is remembered (per origin), so the
// pickers are not offered again.
//
// loopmarket's page copies this file in (its build.py), as it does swarm.js.

export class LocalFile {
  // input: a hidden <input type="file">; types: the pickers' file types;
  // pickers: false to skip them up front (in Freedom, say);
  // refusedKey: where a refusal is remembered.
  constructor({ input, types, pickers = true, refusedKey = "local-file-pickers-refused" }) {
    this.input = input;
    this.types = types;
    this.refusedKey = refusedKey;
    this.handle = null;
    this.pickers = pickers && typeof showOpenFilePicker === "function" && !this._refused();
  }

  // Save writes back to the file that was opened (rather than downloading).
  get inPlace() { return Boolean(this.handle); }

  forget() { this.handle = null; }

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
        if (!this.handle) this.handle = await showSaveFilePicker({ suggestedName: name, types: this.types });
        const mode = { mode: "readwrite" };
        if (await this.handle.queryPermission(mode) !== "granted"
            && await this.handle.requestPermission(mode) !== "granted") {
          throw new DOMException("write permission not granted", "NotAllowedError");
        }
        const w = await this.handle.createWritable();
        await w.write(text);
        await w.close();
        return { how: "file", name: this.handle.name };
      } catch (e) {
        if (e.name === "AbortError") return null;
        this._refuse(e);
      }
    }
    download(text, name);
    return { how: "download", name };
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
