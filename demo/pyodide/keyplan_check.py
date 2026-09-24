"""The key plan under Pyodide: publish a store's shares, read them back as
each reader, revoke, post again. Prints one JSON line.

Run by keyplan.mjs, which installs a local ontodag wheel into Pyodide.
Pyodide ships pycryptodome but not coincurve, so this is also the check that
`ontodag.act`'s pure-Python secp256k1 carries the whole key plan: what a
browser page would need to read a friend's shares with no server.
"""

import json
import time

from recordstore import MemoryBytesStore, RecordStore

from ontodag import act, keyplan, prelude, sharing
from ontodag.dag import OntoDAG

t0 = time.time()
d = OntoDAG()
prelude.apply(d)
d.put("posted", ["time"])
for p in ("bob@x", "carol@x", "everyone"):
    d.put(p, [])
d.put("friends", ["bob@x", "carol@x"])
d.put("merger-plans", [])
d.put("employee-info", ["merger-plans", "friends"])
d.put("trip-photos", ["friends", "posted(2026-09-24T10:00:00Z)"])
d.put("posted(2026)", ["bob@x"])
d.put("hello-world", ["everyone", "posted(2026-09-20T08:30:00Z)"])

ada, bob, carol = (bytes([n]) * 32 for n in (1, 2, 3))
principals = {"bob@x": act.public_key(bob), "carol@x": act.public_key(carol),
              "everyone": act.public_key(keyplan.everyone_key())}
store = RecordStore(MemoryBytesStore())
pub = keyplan.Publisher(store, ada)
content = {"trip-photos": b"photos", "hello-world": b"hello"}
pub.publish(d, principals, content=content)


def view(key):
    return keyplan.Reader(RecordStore.at(store.root, store.blobs), key,
                          act.public_key(ada), workers=1).receive()


exact = all(view(k).names == set(sharing.reach(d, [p])) | {p}
            for p, k in (("bob@x", bob), ("carol@x", carol)))
wall = view(bob).timeline() == sharing.timeline(d, ["bob@x"])
_top, carol_keys, _ = keyplan.Reader(store, carol, act.public_key(ada), workers=1).walk()

d.reclassify(["friends"], to=(), from_=["carol@x"])
lazy = pub.publish(d, principals, content=content).rotated == []
d.put("new-post", ["friends", "posted(2026-09-25T03:00:00Z)"])
rotated = pub.publish(d, principals, content=content).rotated
target = pub.node_id("new-post")
record = store.get(keyplan.RECORD_PREFIX + target)
carol_opens = False
for key in carol_keys.values():
    try:
        keyplan.unseal(key, f"{target}|{record['epoch']}", record["box"])
        carol_opens = True
    except ValueError:
        pass

try:
    import coincurve  # noqa: F401
    curve = "coincurve"
except ImportError:
    curve = "pure Python"

print(json.dumps({
    "curve": curve,
    "readers_exact": exact,
    "timeline_equals_server": wall,
    "leaving_rotates_nothing": lazy,
    "next_post_rotated": rotated,
    "carol_with_old_keys_opens_new_post": carol_opens,
    "bob_reads_new_post": "new-post" in view(bob),
    "seconds": round(time.time() - t0, 2),
}))
