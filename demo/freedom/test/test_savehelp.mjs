// node demo/freedom/test/test_savehelp.mjs
// Checks savehelp.js's choices: no help where the page saves back to files,
// both settings in Brave, the download setting alone in Freedom and
// elsewhere, and Brave's flag noticed once after a relaunch.
const kept = new Map();
globalThis.localStorage = {
  getItem: (k) => (kept.has(k) ? kept.get(k) : null),
  setItem: (k, v) => kept.set(k, String(v)),
  removeItem: (k) => kept.delete(k),
};
const { BRAVE_DOWNLOADS, BRAVE_FLAG, FREEDOM_SETTINGS, flagJustTurnedOn, isBrave, saveAdvice } = await import("../savehelp.js");

let failures = 0;
const check = (ok, what) => { console.log(`${ok ? "ok  " : "FAIL"} ${what}`); if (!ok) failures++; };

check(saveAdvice({ pickers: true, brave: true }) === null, "no help where Save writes back (Chrome, Brave with the flag)");
const brave = saveAdvice({ pickers: false, brave: true });
check(brave.ask.address === BRAVE_DOWNLOADS && brave.flag.address === BRAVE_FLAG, "Brave: ask where to save, and the flag");
const freedom = saveAdvice({ pickers: false, freedom: true });
check(freedom.ask.address === FREEDOM_SETTINGS && freedom.flag === null && /#671/.test(freedom.waits),
      "Freedom: ask where to save; saving back waits for #671");
const other = saveAdvice({ pickers: false });
check(other.ask.address === null && other.flag === null && /Firefox/.test(other.ask.path) && /Safari/.test(other.ask.path),
      "elsewhere: the download setting, in words");
check(await isBrave({ brave: { isBrave: async () => true } }) === true, "Brave is recognised");
check(await isBrave({}) === false && await isBrave(undefined) === false, "other browsers are not Brave");
check(await isBrave({ brave: { isBrave: async () => { throw new Error("no"); } } }) === false, "a failing check is not Brave");
check(flagJustTurnedOn({ brave: true, pickers: true }) === false, "the flag is not announced unless the person asked");
localStorage.setItem("ontodag-brave-flag-asked", "1");
check(flagJustTurnedOn({ brave: true, pickers: false }) === false, "not while Brave still has no pickers");
check(flagJustTurnedOn({ brave: true, pickers: true }) === true, "announced once the pickers are there");
check(flagJustTurnedOn({ brave: true, pickers: true }) === false, "and only once");

if (failures) { console.log(`${failures} failed`); process.exit(1); }
console.log("all passed");
