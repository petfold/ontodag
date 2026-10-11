// The read-only page in real Freedom Browser, run from a Freedom checkout.
//
//   node demo/freedom/freedom_check.cjs REF [FREEDOM_DIR] [--connect]
//
// REF is the page's Swarm reference (build.py --publish). FREEDOM_DIR is a
// freedom-browser checkout with its node_modules (default: beside this
// repository). Freedom is launched as its own live tests launch it
// (test-e2e/live-fixtures.js): a throwaway profile, and the Bee node at
// 127.0.0.1:1633 chosen as its external Swarm node, so the page reads
// through Freedom's real window.swarm provider from that node. The page is
// opened at bzz://REF/ through the address bar; its answers are printed as
// JSON (and to report.json in the throwaway profile), with a screenshot.
// The page is visited twice in one profile: the second visit shows what the
// chunks kept in IndexedDB save. With --connect the page asks Freedom for
// access and the check approves Freedom's prompt, which raises the read
// budget from 120 to 600 reads a minute.

const path = require("path");
const fs = require("fs");
const os = require("os");
const { createRequire } = require("module");

const positional = process.argv.slice(2).filter((a) => !a.startsWith("--"));
const connect = process.argv.includes("--connect");
const ref = positional[0];
const freedomDir = path.resolve(positional[1] || path.join(__dirname, "..", "..", "..", "freedom-browser"));
if (!/^[0-9a-f]{64}$/.test(ref || "")) {
  console.error("usage: node freedom_check.cjs REF [FREEDOM_DIR]");
  process.exit(2);
}
const { _electron: electron } = createRequire(path.join(freedomDir, "package.json"))("@playwright/test");

const QUERIES = [
  ["node", "fruit"], ["node", "food"], ["node", "durian-not-a-category"],
  ["get", "berry"], ["get", "fruit produce"], ["get", "physical-object"], ["below", "apple", "food"], ["below", "apple", "tool"],
];

function inPage(window, code) {
  return window.evaluate(async (snippet) => {
    const wv = document.querySelector("webview:not(.hidden)");
    if (!wv || typeof wv.executeJavaScript !== "function") return { error: "no webview" };
    try { return await wv.executeJavaScript(snippet); } catch (e) { return { error: String(e) }; }
  }, code);
}

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ontodag-freedom-"));
  const dirs = Object.fromEntries(["userData", "ant-data", "ipfs-data", "identity"].map((d) => {
    const p = path.join(tmp, d); fs.mkdirSync(p, { recursive: true }); return [d, p];
  }));
  fs.writeFileSync(path.join(dirs.userData, "settings.json"), JSON.stringify({
    startIpfsAtLaunch: false, startRadicleAtLaunch: false, startTorAtLaunch: false,
  }));
  fs.writeFileSync(path.join(dirs.userData, "external-node-decisions.json"), JSON.stringify({
    bee: { choice: "external", endpoints: ["http://127.0.0.1:1633"] },
  }));
  const app = await electron.launch({
    args: ["."], cwd: freedomDir, timeout: 90_000,
    env: {
      ...process.env,
      FREEDOM_TEST_USER_DATA: dirs.userData, FREEDOM_ANT_DATA: dirs["ant-data"],
      FREEDOM_IPFS_DATA: dirs["ipfs-data"], FREEDOM_IDENTITY_DATA: dirs.identity,
      ELECTRON_DISABLE_SECURITY_WARNINGS: "true", LANG: "en_US.UTF-8",
    },
  });
  const out = { ref, profile: tmp, connect, visits: [] };
  try {
    const window = await app.firstWindow();
    await window.waitForLoadState("domcontentloaded");
    const input = window.locator('[data-test="address-input"]');
    await input.waitFor({ state: "visible", timeout: 60_000 });
    for (const visit of [1, 2]) {
      const v = { visit };
      out.visits.push(v);
      await input.click();
      await input.fill(`bzz://${ref}/`);
      await input.press("Enter");
      const started = Date.now();
      let ready = null;
      await new Promise((r) => setTimeout(r, 1500));
      while (Date.now() - started < 240_000) {
        ready = await inPage(window, "window.ontodagPage ? window.ontodagPage.ready : null");
        if (ready === true || ready === false) break;
        await new Promise((r) => setTimeout(r, 2000));
      }
      v.ready = ready;
      v.seconds_to_ready = (Date.now() - started) / 1000;
      v.source = await inPage(window, "document.getElementById('source').textContent");
      v.provider = await inPage(window, "Boolean(window.swarm && window.swarm.isFreedomBrowser)");
      if (ready !== true) {
        v.status = await inPage(window, "document.getElementById('status').textContent");
        break;
      }
      if (connect && visit === 1) {
        await inPage(window, "window.ontodagPage.connect(), true");
        const approve = window.locator("#swarm-connect-approve");
        await approve.waitFor({ state: "visible", timeout: 30_000 });
        await window.waitForFunction(() => !document.getElementById("swarm-connect-approve").disabled, null, { timeout: 30_000 });
        await approve.click();
        await new Promise((r) => setTimeout(r, 1500));
        v.connected = await inPage(window, "document.getElementById('connect').textContent");
      }
      v.answers = [];
      for (const [fn, ...args] of QUERIES) {
        const t = Date.now();
        const a = await inPage(window, `window.ontodagPage.call(${JSON.stringify(fn)}, ...${JSON.stringify(args)})`);
        const brief = a && a.names ? { count: a.count } : a && a.below && Array.isArray(a.below)
          ? { below: a.below.length } : a;
        v.answers.push({ call: [fn, ...args], ms: Date.now() - t, answer: brief });
      }
      v.stats = await inPage(window, "window.ontodagPage.stats()");
      v.status = await inPage(window, "document.getElementById('status').textContent");
      await window.screenshot({ path: path.join(tmp, `visit${visit}.png`) });
    }
  } finally {
    await app.close().catch(() => {});
  }
  fs.writeFileSync(path.join(tmp, "report.json"), JSON.stringify(out, null, 1));
  console.log(JSON.stringify(out, null, 1));
}

main().catch((e) => { console.error(e); process.exit(1); });
