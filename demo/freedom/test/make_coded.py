"""Erasure-coded uploads for test_swarm.mjs's live part: random data posted
to a Bee node at each redundancy level, so the page's joiner is checked
against trees Bee itself coded. Needs BEE_API and BEE_BATCH (spends a few
hundred chunks of postage)."""

import hashlib
import json
import os
import random
import sys
import urllib.request

api = os.environ.get("BEE_API", "http://localhost:1633").rstrip("/")
batch = os.environ["BEE_BATCH"]
rng = random.Random(20261012)
cases = []
for level in (0, 1, 2, 3, 4):
    for size in (10_000, 300_000):
        data = bytes(rng.getrandbits(8) for _ in range(size))
        req = urllib.request.Request(f"{api}/bytes", data=data, method="POST", headers={
            "Content-Type": "application/octet-stream", "Swarm-Postage-Batch-Id": batch,
            "Swarm-Redundancy-Level": str(level)})
        with urllib.request.urlopen(req, timeout=300) as res:
            ref = json.load(res)["reference"]
        cases.append({"level": level, "size": size, "ref": ref, "sha256": hashlib.sha256(data).hexdigest()})
json.dump({"base": api, "cases": cases}, sys.stdout)
