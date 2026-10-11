"""Chunk trees for test_swarm.mjs, made by swarmfs's splitter (the same one
recordstore's Swarm addressing uses), so the page's joiner and address check
are tested against the reference implementation, not against themselves.
Without swarmfs, a splitter on pycryptodome's keccak stands in, checked
against swarmfs's where both are present (`--compare`)."""

import hashlib
import json
import random
import sys


def _keccak(data):
    from Crypto.Hash import keccak
    return keccak.new(digest_bits=256, data=data).digest()


def _bmt_root(payload):
    level = [payload.ljust(4096, b"\0")[i:i + 32] for i in range(0, 4096, 32)]
    while len(level) > 1:
        level = [_keccak(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def _chunk(span, payload):
    head = span.to_bytes(8, "little")
    return _keccak(head + _bmt_root(payload)), head + payload


def split_without_swarmfs(data):
    """Swarm's splitter on pycryptodome's keccak, for where swarmfs is not
    installed (CI has pycryptodome through the `act` extra): leaves of 4,096
    bytes, intermediate chunks of up to 128 references, and a group of one
    promoted a level rather than wrapped, as Bee's splitter does."""
    chunks = {}
    if not data:
        address, wire = _chunk(0, b"")
        return address, {address: wire}
    level = []
    for i in range(0, len(data), 4096):
        address, wire = _chunk(len(data[i:i + 4096]), data[i:i + 4096])
        chunks[address] = wire
        level.append((address, len(data[i:i + 4096])))
    while len(level) > 1:
        upper = []
        for i in range(0, len(level), 128):
            group = level[i:i + 128]
            if len(group) == 1:
                upper.append(group[0])
                continue
            span = sum(size for _a, size in group)
            address, wire = _chunk(span, b"".join(a for a, _s in group))
            chunks[address] = wire
            upper.append((address, span))
        level = upper
    return level[0][0], chunks


try:
    from swarmfs.splitter import split
except ImportError:
    split = split_without_swarmfs

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
if "--compare" in sys.argv:
    from swarmfs.splitter import split as reference
    rng = random.Random(20261011)
    for size in (0, 1, 31, 32, 4095, 4096, 4097, 8192, 4096 * 128, 4096 * 128 + 1, 600_000, 4096 * 128 * 128 + 5):
        data = bytes(rng.getrandbits(8) for _ in range(size))
        ours, theirs = split_without_swarmfs(data), reference(data)
        assert ours[0] == theirs[0] and ours[1] == theirs[1], size
    print("the stand-in splitter agrees with swarmfs's", file=sys.stderr)
else:
    json.dump(cases, sys.stdout)
