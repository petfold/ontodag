"""What one lazy rotation writes, by kind, in ontodag.keyplan.

SHARING_ON_SWARM §14.2. The group of §4.3 in today's model (members filed
under the group, so `shared-with(friend)` is below each member's term): 50
members, 1,000 items in nested folders, 15% of them with two parents. One
member leaves, then a post arrives in the group, then one in the deepest
folder. For each publication it counts the records written: tokens into
the group's term, tokens out of it, other tokens, node records, grantee
entries. It also counts the tokens re-minted from a rotated node to a
child that kept its key: what an epoch chain, the new key wrapping the old,
would leave alone at the price of one chain token per rotated node.

  python experiments/keyplan_rotation_cost.py

Needs the `act` extra. In memory; under ten seconds.
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from recordstore import MemoryBytesStore, RecordStore

from ontodag import keyplan, prelude
from ontodag.act import public_key
from ontodag.dag import OntoDAG

TERM = "shared-with(friend)"


def build():
    rnd = random.Random(7)
    d = OntoDAG()
    prelude.apply(d)
    d.put("reversed-dimension", ["dimension"])
    d.put("shared-with", ["reversed-dimension"])
    d.put("person", [])
    d.put("friend", ["person"])
    members = [f"m{i}@x" for i in range(50)]
    for m in members:
        d.put(m, ["friend"])
    folders, depth, above = [TERM], {TERM: 0}, {TERM: set()}
    for i in range(1000):
        ps = [folders[rnd.randrange(len(folders))]]
        if rnd.random() < 0.15 and len(folders) > 1:
            ps.append(folders[rnd.randrange(len(folders))])
        name = f"item{i}"
        d.put(name, sorted(set(ps)))
        depth[name] = 1 + max(depth[p] for p in ps)
        above[name] = set().union(*(above[p] | {p} for p in ps)) - {TERM}
        if i % 25 == 0:
            folders.append(name)
    return d, members, folders, depth, above


def changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def tally(pub, keys, before, rotated):
    term = pub.node_id(TERM)
    rotated = {pub.node_id(n) for n in rotated}
    out = {"into the term": 0, "out of the term": 0, "other tokens": 0,
           "records": 0, "grantee entries": 0, "re-minted to a kept key": 0}
    for k in keys:
        if k.startswith(keyplan.NODE_PREFIX) and "/t/" in k:
            u, v = k[len(keyplan.NODE_PREFIX):].split("/t/")
            out["into the term" if v == term else
                "out of the term" if u == term else "other tokens"] += 1
            if u in rotated and v not in rotated and k in before:
                out["re-minted to a kept key"] += 1
        elif k.startswith(keyplan.NODE_PREFIX):
            out["records"] += 1
        elif k.startswith(keyplan.GRANT_PREFIX):
            out["grantee entries"] += 1
    return out


def main():
    keys = random.Random("keys-7")

    def rng(n):
        return bytes(keys.getrandbits(8) for _ in range(n))

    d, members, folders, depth, above = build()
    principals = {m: public_key(rng(32)) for m in members}
    pub = keyplan.Publisher(RecordStore(MemoryBytesStore()), rng(32), rng=rng)
    pub.publish(d, principals)
    print(f"the group's term: {len(keyplan.children(d, TERM))} children, "
          f"{sum(1 for _u, v in pub._plan if v == TERM)} tokens into it")

    deep = max(folders[1:], key=lambda f: (depth[f], len(above[f])))
    steps = [
        ("m0 leaves the group",
         lambda: d.reclassify(["m0@x"], to=["person"], from_=["friend"])),
        ("a post in the group", lambda: d.put("new-note", [TERM])),
        (f"a post in the deepest folder ({depth[deep]} levels down, "
         f"{len(above[deep])} folders above it)",
         lambda: d.put("new-deep-note", [deep])),
    ]
    for label, edit in steps:
        edit()
        before = dict(pub.store.items("kp/"))
        out = pub.publish(d, principals)
        counts = tally(pub, changed(before, dict(pub.store.items("kp/"))),
                       before, out.rotated)
        print(f"\n{label}: {len(out.rotated)} rotated, {out.written} written, "
              f"{out.deleted} deleted")
        for kind, n in counts.items():
            print(f"  {kind:23} {n:5}")
        if out.rotated:
            chained = out.written - counts["re-minted to a kept key"] + len(out.rotated)
            print(f"  with an epoch chain    {chained:5} written (counted, not built)")


if __name__ == "__main__":
    main()
