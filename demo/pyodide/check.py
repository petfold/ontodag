#!/usr/bin/env python3
"""Is a browser a peer? Build the same knowledge natively and under Pyodide
(node + the pyodide package, installing ontodag from PyPI) and compare the
canonical roots. Exit 0 iff they agree.

    cd demo/pyodide && npm install && cd -
    python3 demo/pyodide/check.py [VERSION]

VERSION pins the PyPI release Pyodide installs (default: latest). The native
side runs whatever `import ontodag` resolves to, so pass the version that
is installed here when comparing a release rather than a checkout.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    native = json.loads(subprocess.check_output(
        [sys.executable, os.path.join(HERE, "peer_check.py")], text=True))
    cmd = ["node", os.path.join(HERE, "check.mjs")] + sys.argv[1:2]
    wasm = json.loads(subprocess.check_output(cmd, text=True, cwd=HERE))
    for side, r in (("native", native), ("pyodide", wasm)):
        print(f"{side:8} ontodag {r['ontodag']} registry {r['registry']} "
              f"answer {r['answer']} below {r['below']}\n         root {r['root']}")
    if native["root"] == wasm["root"]:
        print("ROOTS AGREE: the browser is a peer")
        return 0
    print("ROOTS DIFFER: something about the encoding differs under wasm")
    return 1


if __name__ == "__main__":
    sys.exit(main())
