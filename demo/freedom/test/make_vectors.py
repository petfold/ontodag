"""Chunk trees for test_swarm.mjs, made by swarmfs's splitter (the same one
recordstore's Swarm addressing uses), so the page's joiner and address check
are tested against the reference implementation, not against themselves."""

import hashlib
import json
import random
import sys

from swarmfs.splitter import split

rng = random.Random(20261011)
cases = []
for size in (0, 1, 31, 32, 4095, 4096, 4097, 8192, 4096 * 128, 4096 * 128 + 1, 600_000):
    data = bytes(rng.getrandbits(8) for _ in range(size))
    root, chunks = split(data)
    cases.append({
        "size": size,
        "root": root.hex(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "chunks": {a.hex(): c.hex() for a, c in chunks.items()},
    })
json.dump(cases, sys.stdout)
