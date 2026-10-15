// Help for saving where the person wants, in a browser that lets a page
// save only by downloading (BROWSER.md §14.1). A page cannot change a
// browser's settings or open its settings pages, so this says which setting
// helps, copies its address to paste into a new tab, and asks before
// suggesting Brave's flag, which applies to every site.
//
// - Ask where to save (Brave, Freedom from v0.8.5, Firefox, Safari): every
//   download becomes a save dialog, so a file goes straight into the folder
//   chosen, and replacing the old copy is asked.
// - Brave's flag for the File System Access API: Save then writes back to
//   the file, as in Chrome.

export const BRAVE_DOWNLOADS = "brave://settings/downloads";
export const BRAVE_FLAG = "brave://flags/#file-system-access-api";
export const FREEDOM_SETTINGS = "freedom://settings";

const OFF_KEY = "ontodag-savehelp-off";
const FLAG_KEY = "ontodag-brave-flag-asked";

// What helps, or null where the page already saves back to files.
export function saveAdvice({ pickers, brave = false, freedom = false }) {
  if (pickers) return null;
  if (brave) {
    return {
      browser: "Brave",
      ask: { path: "Settings → Downloads → “Ask where to save each file before downloading”", address: BRAVE_DOWNLOADS },
      flag: { address: BRAVE_FLAG },
    };
  }
  if (freedom) {
    return {
      browser: "Freedom",
      ask: { path: "Settings → Downloads → “Ask where to save each file” (on a computer, Freedom 0.8.5 or later; on Android too)", address: FREEDOM_SETTINGS },
      flag: null,
      waits: "Saving back to the same file comes with Freedom 0.8.8 (freedom-browser#671).",
    };
  }
  return {
    browser: "your browser",
    ask: {
      path: "In Firefox: Settings → General → Downloads → “Always ask you where to save files”. "
        + "In Safari: Settings → General → File download location → “Ask for each download”.",
      address: null,
    },
    flag: null,
  };
}

export async function isBrave(nav = globalThis.navigator) {
  try {
    return Boolean(nav && nav.brave && typeof nav.brave.isBrave === "function" && await nav.brave.isBrave());
  } catch {
    return false;
  }
}

function stored(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function store(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* storage off: the help just shows again */ }
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) e.append(c);
  return e;
}

// An address with a button that copies it; where the clipboard is refused,
// the address is selected for the person to copy.
function addressRow(address, label, after) {
  const field = el("input", { class: "addr", readonly: "", value: address, "aria-label": "address to paste" });
  const button = el("button", { type: "button" }, label);
  const note = el("span", { class: "muted" }, "then paste it into a new tab's address bar");
  button.onclick = async () => {
    try {
      await navigator.clipboard.writeText(address);
      note.textContent = "Copied. Paste it into a new tab's address bar.";
    } catch {
      field.select();
      note.textContent = "Press Ctrl+C (⌘C on a Mac) to copy it, then paste it into a new tab's address bar.";
    }
    if (after) after();
  };
  return el("div", { class: "bar" }, button, field, note);
}

export class SaveHelp {
  // dialog: an empty <dialog>; advise: () => saveAdvice(...), asked each
  // time, since a refusal of the pickers can come later.
  constructor({ dialog, advise }) {
    this.dialog = dialog;
    this.advise = advise;
    this.offered = false;
  }

  get available() { return Boolean(this.advise()); }

  // After a save that was a download: once per visit, and never after the
  // person said not to.
  offer() {
    if (!this.available || this.offered || stored(OFF_KEY) === "1") return false;
    this.offered = true;
    this.open();
    return true;
  }

  open() {
    const a = this.advise();
    if (!a) return;
    const parts = [
      el("h2", {}, "Save into a folder you choose"),
      el("p", {}, `${a.browser === "your browser" ? "This browser" : a.browser} lets this page save only by downloading, `
        + "so what it saves goes to your Downloads folder. A setting changes that. The page cannot change it for you; "
        + "it can show you where it is."),
      el("h3", {}, "Ask where to save"),
      el("p", {}, "Each save then asks which folder, and asks before replacing the copy already there. Nothing else changes."),
      el("p", {}, a.ask.path),
    ];
    if (a.ask.address) parts.push(addressRow(a.ask.address, "Copy the address"));
    if (a.waits) parts.push(el("p", { class: "muted" }, a.waits));
    if (a.flag) {
      const steps = el("ol", { class: "hidden" },
        el("li", {}, "Paste the address into a new tab's address bar."),
        el("li", {}, "Set the File System Access API entry to Enabled."),
        el("li", {}, "Press Relaunch. When this page opens again, Save writes back to your file."));
      parts.push(
        el("h3", {}, "Or: save back to the same file, as Chrome does"),
        el("p", {}, "Brave keeps the File System Access API off; one flag turns it on. The flag is for every site. "
          + "A site still has to ask you, and reaches only a file or folder you pick yourself."),
        el("p", {}, "Turn it on?"),
        addressRow(a.flag.address, "Yes, show me how", () => { steps.classList.remove("hidden"); store(FLAG_KEY, "1"); }),
        steps,
      );
    }
    const off = el("input", { type: "checkbox", id: "savehelp-off" });
    off.checked = stored(OFF_KEY) === "1";
    off.onchange = () => store(OFF_KEY, off.checked ? "1" : null);
    const close = el("button", { type: "button", class: "primary" }, "Close");
    close.onclick = () => this.dialog.close();
    parts.push(el("div", { class: "bar dialogfoot" },
      el("label", { for: "savehelp-off" }, off, " Don't show this after saving"), close));
    this.dialog.replaceChildren(...parts);
    if (!this.dialog.open) this.dialog.showModal();
  }
}

// After Brave relaunched with the flag on: true once, so the page can say
// that Save now writes back.
export function flagJustTurnedOn({ brave, pickers }) {
  if (!brave || !pickers || stored(FLAG_KEY) !== "1") return false;
  store(FLAG_KEY, null);
  return true;
}
