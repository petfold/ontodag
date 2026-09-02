"""The peerhood check (BROWSER.md §8 step 3), shared by both sides.

The same knowledge is built through the public API and committed to a
memory record store; the JSON printed carries the canonical root. Run
natively it says what a laptop computes; run under Pyodide (see check.mjs)
it says what a browser computes. `python3 demo/pyodide/check.py` runs both
and compares — equal roots mean a browser is a peer, not a silo.
"""
import json
from importlib.metadata import version

import ontodag
from ontodag.dimensions import REGISTRY_VERSION
from ontodag.prelude import apply
from recordstore import MemoryBytesStore, RecordStore

dag = ontodag.EagerOntoDAG(RecordStore(MemoryBytesStore()))
apply(dag)
dag.put("from", ["prefix-dimension"])
dag.put("to", ["prefix-dimension"])
dag.put("transport", [])
dag.put("flight", ["transport"])
dag.put("BA2551", ["flight", "from(EU-UK-London)", "to(EU-IT-Rome)",
                   "duration(155min)"])
dag.put("N42", ["transport", "from(EU-UK-London)", "to(EU-IT-Rome)",
                "duration(30h)"])
print(json.dumps({
    "ontodag": version("ontodag"),
    "registry": REGISTRY_VERSION,
    "answer": sorted(x.name for x in dag.get(["transport", "duration(..10h)"])),
    "below": dag.is_below("BA2551", "duration(..3h)"),
    "root": dag.commit(),
}))
