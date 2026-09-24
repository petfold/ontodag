"""Spike: derive ACT tokens from an OntoDAG store, and rotate keys on loss.

For docs/plans/SHARING_ON_SWARM.md, which reports the results (§4.3, §12).

Question 1 (correctness): if the author publishes a token for every edge of
the combined order below its principals (asserted edges AND computed hops
between present typed values), and one grantee entry per principal, does a
reader derive exactly the keys of reach(store, [principal]) ∪ {principal}?

Question 2 (edge removal in a DAG): after an edit, which nodes need new
keys, and when? Four rules, run on the same random stores and the same
random edits (the store and its edits come from one RNG, key material from
another, so the rules differ only in what they rotate):

  eager      rotate every surviving node some principal lost, at once
  internal   rotate only the lost nodes that have children, as
             KeyGraph.revoke does today (nodes with outgoing tokens)
  lazy       rotate a lost node only before something new is wrapped under
             it, and then upward to a fixpoint: rotating it re-wraps its new
             key under its parents, which may be lost and unrotated too
  lazy-once  lazy, without the fixpoint

After every edit, for a reader that kept every key it ever derived:

  new keys      can it derive a key minted after it last had that node in
                reach? The property that matters.
  current keys  can it derive the current key of a node outside its reach?
                Eager's stronger promise. Lazy breaks it on purpose, for
                nodes with nothing new under them.

Run from the repository root:

  python experiments/keyplan_spike.py                  # all of it
  python experiments/keyplan_spike.py --seeds 0:20     # a quick run
  python experiments/keyplan_spike.py --only big       # the one large group
"""

import argparse
import os
import random
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ontodag import prelude, sharing
from ontodag.act import (GRANT_PREFIX, TOKEN_PREFIX, KeyGraph, Resolver,
                         node_id, public_key, unwrap)
from ontodag.dag import OntoDAG

RULES = ("eager", "internal", "lazy", "lazy-once")


class MemStore:
    def __init__(self):
        self.d = {}

    def put(self, k, v):
        self.d[k] = v

    def get(self, k):
        return self.d[k]

    def delete(self, k):
        self.d.pop(k, None)

    def keys(self, prefix=""):
        return [k for k in list(self.d) if k.startswith(prefix)]

    def commit(self, **kw):
        return "mem"


def combined_children(dag, name):
    node = dag.nodes[name]
    out = {c.name for c in node.neighbors}
    out |= {c.name for c in dag._computed_children(node)}
    return out


def desired_edges(dag, principals):
    """The token plan: every edge of the combined order from a principal, or
    from a node in some principal's reach, to each of its children."""
    edges = set()
    for p in principals:
        if p not in dag.nodes:
            continue
        for u in {p} | set(sharing.reach(dag, [p])):
            for c in combined_children(dag, u):
                edges.add((u, c))
    return edges


class Author:
    """A KeyGraph kept equal to the plan derived from the store. Records the
    step at which each node's current key was minted."""

    def __init__(self, principals, rng):
        self.store = MemStore()
        self.kg = KeyGraph(self.store, org_private_key=rng(32), rng=rng)
        self.principals = principals          # principal node -> reader public key
        self.rotations = 0
        self.minted = {}
        self.step = 0
        ensure, rotate = self.kg.ensure, self.kg.rotate

        def ensure_(name):
            self.minted.setdefault(name, self.step)
            return ensure(name)

        def rotate_(name):
            rotate(name)
            self.minted[name] = self.step
        self.kg.ensure, self.kg.rotate = ensure_, rotate_

    def publish(self, dag):
        want = desired_edges(dag, self.principals)
        by_id = {node_id(n): n for n in self.kg.export_keys()}
        for key in self.store.keys(TOKEN_PREFIX):
            u_id, v_id = key[len(TOKEN_PREFIX):].split("/")
            if (by_id.get(u_id), by_id.get(v_id)) not in want:
                self.store.delete(key)
        for u, v in sorted(want):
            self.kg.link(u, v)                # deterministic: re-minting is a no-op
        for p, pub in sorted(self.principals.items()):
            self.kg.grant(p, pub)
        return want

    def rotate(self, names):
        for n in sorted(names):
            self.kg.rotate(n)
            self.rotations += 1


def due_for(rule, dag, lost, stale, plan, new_plan):
    """The nodes to rotate before publishing `new_plan`. `stale` holds lost
    nodes not yet rotated (lazy rules only) and is updated in place."""
    if rule == "eager":
        return set(lost)
    if rule == "internal":
        return {n for n in lost if combined_children(dag, n)}
    stale |= lost
    due = set()
    while True:
        # a token is minted for every new edge, and re-minted for every edge
        # into a node being rotated; a stale node that would wrap one rotates
        minting = (new_plan - plan) | {(u, v) for (u, v) in new_plan if v in due}
        more = {u for (u, v) in minting if u in stale} - due
        if not more:
            break
        due |= more
        if rule == "lazy-once":
            break
    stale -= due
    return due


def closure(store, known):
    """Everything derivable from `known` (id -> set of keys) over the current
    tokens, trying every key held for a node: an attacker with old keys."""
    known = {k: set(v) for k, v in known.items()}
    out = {}
    for key in store.keys(TOKEN_PREFIX):
        u_id, v_id = key[len(TOKEN_PREFIX):].split("/")
        out.setdefault(u_id, []).append((v_id, bytes.fromhex(store.get(key)["token"])))
    changed = True
    while changed:
        changed = False
        for u_id, ks in list(known.items()):
            for v_id, token in out.get(u_id, ()):
                for k in list(ks):
                    cand = unwrap(k, v_id, token)
                    s = known.setdefault(v_id, set())
                    if cand not in s:
                        s.add(cand)
                        changed = True
    return known


def random_store(rnd, n_items=14):
    dag = OntoDAG()
    prelude.apply(dag)
    dag.put("posted", ["time"])
    principals = ["a@x", "b@x", "c@x"]
    groups = ["g1", "g2"]
    for p in principals:
        dag.put(p, [])
    for g in groups:
        dag.put(g, rnd.sample(principals, rnd.randint(1, 2)))
    if rnd.random() < 0.5:
        dag.put("g1", ["g2"])                # nested audiences
    items = [f"n{i}" for i in range(n_items)]
    for i, it in enumerate(items):
        pool = items[:i] + groups + principals
        dag.put(it, rnd.sample(pool, min(len(pool), rnd.randint(0, 2))))
    # typed values: a share of "all 2026 posts", and posts at times inside it
    if rnd.random() < 0.6:
        dag.put("posted(2026)", [rnd.choice(principals + groups)])
        for it in rnd.sample(items, 3):
            day = rnd.randint(1, 28)
            dag.put(it, [f"posted(2026-09-{day:02d}T10:00:00Z)"])
    return dag, principals, groups, items


def random_edit(rnd, dag, principals, groups, items):
    names = [n for n in items + groups if n in dag.nodes]
    kind = rnd.random()
    try:
        if kind < 0.4 and names:                                  # add an edge
            x = rnd.choice(names)
            y = rnd.choice([n for n in names + principals if n != x])
            dag.put(x, [y])
            return f"put {x} {y}"
        if kind < 0.8:                                            # remove an edge
            cands = sorted((x, p.name) for x in names for p in dag.nodes[x].parents
                           if dag.nodes.get(p.name) is p and p.name != dag.root.name)
            if cands:
                x, y = rnd.choice(cands)
                dag.reclassify([x], to=(), from_=[y])
                return f"unfile {x} from {y}"
        if names:                                                 # remove a node (contract)
            x = rnd.choice(names)
            dag.remove(x)
            return f"remove {x}"
    except ValueError:
        return None
    return None


def run(rule, seed, steps=30):
    """One random store under one rule. Returns counts."""
    rnd = random.Random(seed)                                     # the store and its edits
    keys = random.Random(f"keys-{seed}")                          # key material only
    rng = lambda n: bytes(keys.getrandbits(8) for _ in range(n))
    dag, principals, groups, items = random_store(rnd)
    readers = {p: rng(32) for p in principals}
    author = Author({p: public_key(k) for p, k in readers.items()}, rng)
    plan = author.publish(dag)
    stale = set()
    cache = {p: {} for p in principals}           # every key each reader ever derived
    last_access = {p: {} for p in principals}     # name -> last step it was in reach
    c = dict(edits=0, rotations=0, mismatches=0, new=0, new_edits=0,
             current=0, current_edits=0)

    def check(step):
        true = {node_id(n): (n, k) for n, k in author.kg.export_keys().items()
                if n in dag.nodes}                # a deleted node has nothing left to read
        new = current = 0
        for p, priv in readers.items():
            allowed = set(sharing.reach(dag, [p])) | {p}
            walk = Resolver(author.store, priv)._walk()
            if set(walk) != {node_id(n) for n in allowed}:
                c["mismatches"] += 1
            for n in allowed:
                last_access[p][n] = step
            for i, k in walk.items():
                cache[p].setdefault(i, set()).add(k)
            for i, ks in closure(author.store, cache[p]).items():
                if i not in true:
                    continue
                n, k = true[i]
                if n in allowed or k not in ks:
                    continue
                current += 1
                if author.minted[n] > last_access[p].get(n, -1):
                    new += 1
        c["new"] += new
        c["current"] += current
        c["new_edits"] += bool(new)
        c["current_edits"] += bool(current)

    check(0)
    for step in range(1, steps + 1):
        author.step = step
        before = dag.deepcopy()
        if random_edit(rnd, dag, principals, groups, items) is None:
            continue
        c["edits"] += 1
        lost = sharing.losses(before, dag, principals)
        lost = {n for ns in lost.values() for n in ns if n in dag.nodes}
        new_plan = desired_edges(dag, principals)
        author.rotate(due_for(rule, dag, lost, stale, plan, new_plan))
        plan = author.publish(dag)
        check(step)
    c["rotations"] = author.rotations
    return c


def _task(args):
    rule, seed, steps = args
    return rule, run(rule, seed, steps)


def rules_table(seeds, steps, jobs):
    tasks = [(rule, seed, steps) for rule in RULES for seed in seeds]
    total = {rule: dict(stores=0, edits=0, rotations=0, mismatches=0, new=0,
                        new_edits=0, current=0, current_edits=0) for rule in RULES}
    with Pool(jobs) as pool:
        for rule, c in pool.imap_unordered(_task, tasks, chunksize=4):
            t = total[rule]
            t["stores"] += 1
            for k, v in c.items():
                t[k] += v
    print(f"{len(seeds)} random stores (seeds {seeds.start}-{seeds.stop - 1}), "
          f"up to {steps} random edits each, the same edits under every rule\n")
    print(f"{'rule':10} {'edits':>6} {'rotations/edit':>15} {'reach mismatches':>17} "
          f"{'edits exposing new keys':>24} {'edits exposing unrotated keys':>30}")
    for rule in RULES:
        t = total[rule]
        print(f"{rule:10} {t['edits']:6} {t['rotations'] / max(t['edits'], 1):15.2f} "
              f"{t['mismatches']:17} {t['new_edits']:24} {t['current_edits']:30}")
    return total


def big_group():
    """50 members, 1,000 items in nested folders, some with two parents; one
    member leaves, then two new posts arrive. Eager against lazy."""
    def build():
        rnd = random.Random(7)
        keys = random.Random("keys-7")
        rng = lambda n: bytes(keys.getrandbits(8) for _ in range(n))
        dag = OntoDAG()
        members = [f"m{i}@x" for i in range(50)]
        for m in members:
            dag.put(m, [])
        dag.put("group", members)
        folders = ["group"]
        for i in range(1000):
            ps = [folders[rnd.randrange(len(folders))]]
            if rnd.random() < 0.15 and len(folders) > 1:
                ps.append(folders[rnd.randrange(len(folders))])
            dag.put(f"item{i}", sorted(set(ps)))
            if i % 25 == 0:
                folders.append(f"item{i}")
        readers = {m: rng(32) for m in members}
        author = Author({m: public_key(s) for m, s in readers.items()}, rng)
        return dag, members, folders, readers, author

    def folders_above(dag, name):
        """The longest path from the group down to `name`, and how many
        folders sit above it."""
        memo, seen = {}, set()

        def length(n):
            if n == "group":
                return 0
            if n not in memo:
                ups = [p.name for p in dag.nodes[n].parents
                       if p.name == "group" or p.name.startswith("item")]
                seen.update(ups)
                memo[n] = 1 + max(length(p) for p in ups)
            return memo[n]
        return length(name), len(seen - {"group"})

    def commit(rule, dag, members, author, before, state):
        lost = sharing.losses(before, dag, members)
        lost = {n for ns in lost.values() for n in ns if n in dag.nodes}
        new_plan = desired_edges(dag, members)
        snapshot = dict(author.store.d)
        due = due_for(rule, dag, lost, state["stale"], state["plan"], new_plan)
        author.rotate(due)
        state["plan"] = author.publish(dag)
        written = (sum(1 for k, v in author.store.d.items() if snapshot.get(k) != v)
                   + sum(1 for k in snapshot if k not in author.store.d))
        return len(due), written

    for rule in ("eager", "lazy"):
        dag, members, folders, readers, author = build()
        t = time.time()
        state = {"plan": author.publish(dag), "stale": set()}
        t_pub = time.time() - t
        if rule == "eager":
            t = time.time()
            n_keys = len(Resolver(author.store, readers["m3@x"])._walk())
            t_walk = time.time() - t
            print(f"publish: {len(author.store.keys(TOKEN_PREFIX))} tokens, "
                  f"{len(author.store.keys(GRANT_PREFIX))} grantee entries, {t_pub:.1f} s; "
                  f"one member's walk: {n_keys} keys, {t_walk:.2f} s")
        print(f"\n{rule}:")
        before = dag.deepcopy()
        dag.reclassify(["group"], to=(), from_=["m0@x"])          # m0 leaves the group
        n, w = commit(rule, dag, members, author, before, state)
        print(f"  m0 leaves the group:          {n:5} rotations, {w:5} records written "
              f"(of {len(author.store.d)})")
        before = dag.deepcopy()
        dag.put("new-note", ["group"])
        n, w = commit(rule, dag, members, author, before, state)
        print(f"  next post, in the group:      {n:5} rotations, {w:5} records written")
        deep = max(folders, key=lambda f: folders_above(dag, f))
        levels, above = folders_above(dag, deep)
        before = dag.deepcopy()
        dag.put("new-deep-note", [deep])
        n, w = commit(rule, dag, members, author, before, state)
        print(f"  next post, in a folder {levels} levels down, with {above} folders above it: "
              f"{n} rotations, {w} records written")
        exact = all(Resolver(author.store, readers[m]).reachable_ids()
                    == {node_id(x) for x in set(sharing.reach(dag, [m])) | {m}}
                    for m in members[1:])
        shut_out = not ({node_id("new-note"), node_id("new-deep-note")}
                        & Resolver(author.store, readers["m0@x"]).reachable_ids())
        print(f"  the other 49 derive exactly their reach: {exact}; "
              f"m0 derives neither new post: {shut_out}"
              + (f"; lost and not yet rotated: {len(state['stale'])}" if rule == "lazy" else ""))


def _seeds(text):
    a, b = text.split(":")
    return range(int(a), int(b))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seeds", type=_seeds, default=range(0, 200), help="A:B, default 0:200")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--only", choices=("rules", "big"))
    args = ap.parse_args()
    if args.only != "big":
        rules_table(args.seeds, args.steps, args.jobs)
        print()
    if args.only != "rules":
        big_group()
