"""Does Bee 2.8.2 write dispersed replicas of the root for a one-chunk /bytes
upload at level 1? Upload 100 random bytes at levels 1 and 0, then look for
SOC replicas (id = root address with byte 0 replaced by i, owner = the
address of key 0x01 00..00) in the node's local store."""
import os, sys, urllib.request
from eth_account import Account
from Crypto.Hash import keccak

API, BATCH = "http://localhost:1633", sys.argv[1]
OWNER = bytes.fromhex(Account.from_key(bytes([1]) + bytes(31)).address[2:])

def k(b): h = keccak.new(digest_bits=256); h.update(b); return h.digest()

def upload(data, level):
    req = urllib.request.Request(f"{API}/bytes", data, {
        "Swarm-Postage-Batch-Id": BATCH, "Swarm-Deferred-Upload": "false",
        "Swarm-Redundancy-Level": str(level), "Content-Type": "application/octet-stream"})
    import json
    return json.load(urllib.request.urlopen(req, timeout=120))["reference"]

def local(addr):
    try:
        urllib.request.urlopen(f"{API}/chunks/{addr}", timeout=10).read(); return True
    except Exception:
        return False

for level in (1, 0):
    ref = upload(os.urandom(100), level)
    root = bytes.fromhex(ref)
    found = []
    for i in range(32):
        rid = bytes([i]) + root[1:]
        if local(k(rid + OWNER).hex()):
            found.append(i)
    print(f"level {level}: root {ref[:16]}…, replica SOCs found for i in {found} ({len(found)})")
