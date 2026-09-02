// Runs peer_check.py under Pyodide in node, installing ontodag from PyPI
// through micropip exactly as a browser would. Prints the one JSON line.
//   npm install   (once; pyodide is the only dependency)
//   node check.mjs [VERSION]
import { loadPyodide } from "pyodide";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const spec = process.argv[2] ? `ontodag==${process.argv[2]}` : "ontodag";
const t0 = Date.now();
const py = await loadPyodide({ stdout: () => {} });          // loader chatter off stdout
await py.loadPackage("micropip", { messageCallback: () => {} });
await py.pyimport("micropip").install(spec);
const t1 = Date.now();
py.setStdout({ batched: (s) => console.log(s) });
py.runPython(readFileSync(join(here, "peer_check.py"), "utf8"));
console.error(`pyodide ${py.version}: ${spec} installed from PyPI in ${((t1 - t0) / 1000).toFixed(1)}s`);
