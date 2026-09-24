// Runs keyplan_check.py under Pyodide in node: the key plan in a browser's
// Python, with pycryptodome from Pyodide and no coincurve (Pyodide has none).
//   npm install   (once; pyodide is the only dependency)
//   python -m pip wheel ../.. --no-deps -w dist
//   node keyplan.mjs dist/ontodag-*.whl
import { loadPyodide } from "pyodide";
import { readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const wheel = process.argv[2];
if (!wheel) {
  console.error("usage: node keyplan.mjs path/to/ontodag-*.whl");
  process.exit(2);
}
const t0 = Date.now();
const py = await loadPyodide({ stdout: () => {} });
await py.loadPackage(["micropip", "pycryptodome"], { messageCallback: () => {} });
const target = `/tmp/${basename(wheel)}`;
py.FS.writeFile(target, readFileSync(wheel));
await py.pyimport("micropip").install(`emfs:${target}`);
const t1 = Date.now();
py.setStdout({ batched: (s) => console.log(s) });
py.runPython(readFileSync(join(here, "keyplan_check.py"), "utf8"));
console.error(`pyodide ${py.version}: installed in ${((t1 - t0) / 1000).toFixed(1)}s`);
