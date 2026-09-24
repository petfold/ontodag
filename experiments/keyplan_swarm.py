"""The key plan on Swarm: publish a store's shares, read them back as each
reader, revoke, post again (docs/plans/SHARING_ON_SWARM.md, Phase 2).

Ada's store is the author's: a group of two friends, a folder tree of
items shared with them, a share of all her 2026 posts with Bob, and a
public post. Her key plan goes to a Swarm feed through a Bee node. Then,
each on a store opened cold from the feed, with nothing but their own key
and Ada's public key:

  1. Bob, Carol and a stranger read what they're shared (and nothing else);
  2. Carol leaves the group (lazy: nothing rotates yet), and Ada posts in it
     (the group rotates), and Carol, holding every key she ever had, can't
     open the new post while Bob reads it;
  3. a second author, Dan, shares with Bob too, and Bob's inbox merges the
     two walls, read from their two feeds, in `posted` order.

Every read is checked against `sharing.reach`. Times, records written and
blob round trips are printed and saved as JSON.

  python experiments/keyplan_swarm.py --batch <usable batch id>
      [--api http://localhost:1633] [--gateway https://api.gateway.ethswarm.org]
      [--items 120] [--workers 16] [--out results.json]

`--gateway` also reads Bob's shares through a second node that never held
the data, which is closer to what a friend's own node sees.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from recordstore import BeeBytesStore, RecordStore, SwarmFeedPointer

from ontodag import keyplan, prelude, sharing
from ontodag.act import keccak256, public_key, unwrap
from ontodag.dag import OntoDAG


class Counting:
    """A bytes store that counts its calls: `puts`, and `gets` as round
    trips (a `get_many` is one), with `refs` fetched in all."""

    def __init__(self, inner):
        self.inner = inner
        self.puts = self.gets = self.refs = 0
        if hasattr(inner, "put_many"):
            self.put_many = self._put_many
        if hasattr(inner, "get_many"):
            self.get_many = self._get_many

    def put(self, data):
        self.puts += 1
        return self.inner.put(data)

    def _put_many(self, datas):
        datas = list(datas)
        self.puts += len(datas)
        return self.inner.put_many(datas)

    def get(self, ref):
        self.gets += 1
        self.refs += 1
        return self.inner.get(ref)

    def _get_many(self, refs):
        refs = list(refs)
        self.gets += 1
        self.refs += len(refs)
        return self.inner.get_many(refs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def address(private_key):
    """The Ethereum address a secp256k1 key signs feeds as."""
    import coincurve
    pub = coincurve.PublicKey.from_valid_secret(private_key).format(compressed=False)
    return keccak256(pub[1:])[-20:].hex()


def adas_store(items):
    d = OntoDAG()
    prelude.apply(d)
    d.put("posted", ["time"])
    for p in ("bob@x", "carol@x", "everyone"):
        d.put(p, [])
    d.put("friends", ["bob@x", "carol@x"])
    d.put("merger-plans", [])
    folders = ["friends"]
    for i in range(items):
        parent = folders[(i * 7) % len(folders)]
        d.put(f"item{i}", [parent])
        if i % 10 == 0:
            folders.append(f"item{i}")
    d.put("employee-info", ["merger-plans", "friends"])
    d.put("trip-photos", ["friends", "posted(2026-09-24T10:00:00Z)"])
    d.put("posted(2026)", ["bob@x"])
    d.put("note-to-bob", ["bob@x", "posted(2026-09-24T12:15:00Z)"])
    d.put("hello-world", ["everyone", "posted(2026-09-20T08:30:00Z)"])
    content = {"trip-photos": b"Photos from the trip, for friends.",
               "note-to-bob": b"Bob: dinner on Friday?",
               "hello-world": b"Hello, world. This one is public.",
               "employee-info": b"Holidays: 25 days."}
    return d, content


READ_ONLY = "0" * 64   # reads never send a batch; this stops the store looking one up


def open_feed(api, topic, owner):
    blobs = Counting(BeeBytesStore(api, READ_ONLY))
    pointer = SwarmFeedPointer(api, topic, owner=owner)
    return RecordStore(blobs, pointer=pointer), blobs


def read_as(api, topic, owner, key, author_pub, expect=None, workers=16):
    t = time.time()
    store, blobs = open_feed(api, topic, owner)
    t_open = time.time() - t
    got = keyplan.Reader(store, key, author_pub, workers=workers).receive()
    texts = {n: got.content(n) for n in sorted(got.names) if got.content(n)}
    elapsed = time.time() - t
    ok = expect is None or got.names == expect
    return {"names": len(got.names), "exact": ok, "seconds": round(elapsed, 2),
            "feed_seconds": round(t_open, 2), "round_trips": blobs.gets,
            "blobs": blobs.refs, "contents": {n: v.decode() for n, v in texts.items()}}, got


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--api", default="http://localhost:1633")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--gateway")
    ap.add_argument("--items", type=int, default=120)
    ap.add_argument("--workers", type=int, default=16,
                    help="reader threads per level of the walk; 1 reads one key at a time")
    ap.add_argument("--topic", default=f"ontodag-keyplan-demo-{int(time.time())}")
    ap.add_argument("--out")
    args = ap.parse_args()

    ada, bob, carol, stranger = (os.urandom(32) for _ in range(4))
    ada_pub, owner = public_key(ada), address(ada)
    readers = {"bob@x": bob, "carol@x": carol}
    principals = {p: public_key(k) for p, k in readers.items()}
    principals["everyone"] = public_key(keyplan.everyone_key())
    results = {"topic": args.topic, "owner": owner, "items": args.items,
               "workers": args.workers, "steps": []}

    blobs = Counting(BeeBytesStore(args.api, args.batch, deferred_upload=False))
    pointer = SwarmFeedPointer(args.api, args.topic, signer=ada.hex(),
                               postage_batch_id=args.batch)
    store = RecordStore(blobs, pointer=pointer)
    pub = keyplan.Publisher(store, ada)
    dag, content = adas_store(args.items)

    def publish(label):
        before = blobs.puts
        t = time.time()
        out = pub.publish(dag, principals, content=content, message=label)
        step = {"step": label, "publish_seconds": round(time.time() - t, 2),
                "records_written": out.written, "records_deleted": out.deleted,
                "blobs_uploaded": blobs.puts - before, "rotated": out.rotated,
                "stale": out.stale, "shared": out.shared, "root": out.root}
        results["steps"].append(step)
        print(f"\n== {label}: {out.written} records written, {out.deleted} deleted, "
              f"{step['blobs_uploaded']} blobs, rotated {out.rotated or 'nothing'}, "
              f"{out.stale} stale; {step['publish_seconds']} s")
        return step

    def read(step, who, key, expect, api=args.api, where="node"):
        r, got = read_as(api, args.topic, owner, key, ada_pub, expect, args.workers)
        step.setdefault("reads", {})[f"{who} via {where}"] = r
        print(f"   {who:9} via {where}: {r['names']:4} names, exact: {r['exact']}, "
              f"{r['seconds']} s ({r['feed_seconds']} s feed), {r['round_trips']} round trips")
        return got

    def reach(p):
        return set(sharing.reach(dag, [p])) | {p}

    s = publish("first publication")
    read(s, "bob", bob, reach("bob@x"))
    carol_view = read(s, "carol", carol, reach("carol@x"))
    read(s, "stranger", stranger, set())
    public = read(s, "everyone", keyplan.everyone_key(), reach("everyone"))
    if args.gateway:
        read(s, "bob", bob, reach("bob@x"), api=args.gateway, where="gateway")
    print(f"   Carol reads trip-photos: {carol_view.content('trip-photos')!r}")
    print(f"   the public reads: {sorted(public.names)}")

    # every key Carol ever held, walked on the live store
    _top, carol_keys, _ = keyplan.Reader(store, carol, ada_pub).walk()
    held = {i: {k} for i, k in carol_keys.items()}

    dag.reclassify(["friends"], to=(), from_=["carol@x"])
    s = publish("Carol leaves the group")
    read(s, "carol", carol, reach("carol@x"))

    dag.put("new-post", ["friends", "posted(2026-09-25T03:00:00Z)"])
    content["new-post"] = b"A new post for friends, after Carol left."
    s = publish("a new post in the group")
    got = read(s, "bob", bob, reach("bob@x"))
    read(s, "carol", carol, reach("carol@x"))
    print(f"   Bob reads new-post: {got.content('new-post')!r}")

    # Carol, with every key she ever had, against the live tokens
    tokens = {}
    for u, v, token in keyplan.tokens(store):
        tokens.setdefault(u, []).append((v, token))
    changed = True
    while changed:
        changed = False
        for u, ks in list(held.items()):
            for v, token in tokens.get(u, ()):
                for key in list(ks):
                    cand = unwrap(key, v, token)
                    if cand not in held.setdefault(v, set()):
                        held[v].add(cand)
                        changed = True
    target = pub.node_id("new-post")
    record = store.get(keyplan.record_key(target))
    opened = False
    for key in held.get(target, ()):
        try:
            keyplan.unseal(key, f"{target}|{record['epoch']}", record["box"])
            opened = True
        except ValueError:
            pass
    s["carol_with_old_keys_opens_new_post"] = opened
    print(f"   Carol, with every key she ever had, opens new-post: {opened}")

    # a second author, and Bob's inbox: the walls he follows, merged
    dan = os.urandom(32)
    dan_topic = args.topic + "-dan"
    d2 = OntoDAG()
    prelude.apply(d2)
    d2.put("posted", ["time"])
    for p in ("bob@x", "everyone"):
        d2.put(p, [])
    d2.put("climbing-club", ["bob@x"])
    d2.put("route-report", ["climbing-club", "posted(2026-09-24T18:00:00Z)"])
    d2.put("open-day", ["everyone", "posted(2026-09-25T02:00:00Z)"])
    dan_store = RecordStore(Counting(BeeBytesStore(args.api, args.batch, deferred_upload=False)),
                            pointer=SwarmFeedPointer(args.api, dan_topic, signer=dan.hex(),
                                                     postage_batch_id=args.batch))
    t = time.time()
    keyplan.Publisher(dan_store, dan).publish(
        d2, {"bob@x": public_key(bob), "everyone": public_key(keyplan.everyone_key())},
        content={"route-report": b"The north face is dry.", "open-day": b"Open day on Sunday."})
    dan_seconds = round(time.time() - t, 2)
    t = time.time()
    walls = {}
    for label, topic, key_owner, author_pub in (
            ("ada", args.topic, owner, ada_pub),
            ("dan", dan_topic, address(dan), public_key(dan))):
        st, _ = open_feed(args.api, topic, key_owner)
        walls[label] = keyplan.Reader(st, bob, author_pub,
                                      workers=args.workers).receive(public=True)
    inbox = keyplan.inbox(walls)
    results["inbox"] = {"seconds": round(time.time() - t, 2), "dan_publish_seconds": dan_seconds,
                        "posts": [[v, a, n] for v, a, n in inbox]}
    print(f"\n== Bob's inbox, two authors read from Swarm in {results['inbox']['seconds']} s:")
    for value, author, name in inbox:
        text = walls[author].content(name)
        print(f"   {value[7:-1]}  {author}: {name}" + (f" - {text.decode()}" if text else ""))

    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nsaved {args.out}")


if __name__ == "__main__":
    main()
