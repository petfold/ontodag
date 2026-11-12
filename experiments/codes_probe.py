"""The numbers behind docs/plans/CODES_AND_FACTORS.md.

Run from the repository root: ``python3 experiments/codes_probe.py
[probe ...]``. With no argument every probe runs (about a minute). Probes:
shape, codes, trees, tops, filing, put.

The store is the shipped vocabulary (core and the ten domain packs);
`filing` and `put` file a made-up population under it. The codes follow
asserted edges only, as the stored counts do. Where the computed order of
terms can add to them a mark says so and the probe climbs instead, and it
asserts that its answers are then the planner's and the browser's. Times
are wall-clock on whatever machine runs this.
"""
import cProfile
import collections
import os
import pstats
import random
import statistics
import sys
import time

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

from ontodag import browse, dimensions, packs, prelude  # noqa: E402
from ontodag.dag import OntoDAG  # noqa: E402

DOMAINS = ["physics", "mathematics", "chemistry", "biology", "medicine", "ai",
           "economics", "computing", "geography", "space"]
ASPECTS = ["physical-object", "event", "information"]
ITEMS = 30_000


def union():
    dag = OntoDAG()
    prelude.apply(dag)
    for name in ["core", *DOMAINS]:
        dag.merge(packs.adoption_dag(dag, name))
    return dag


def own(dag, node):
    return [p for p in node.parents if dag.nodes.get(p.name) is p]


class Codes:
    """Every node's ancestors and every node's cone as integers used as
    bit sets, over one numbering of the nodes (parents before children)."""

    def __init__(self, dag):
        nodes = list(dag.nodes.values())
        waiting = {node: len(own(dag, node)) for node in nodes}
        ready = sorted((node for node in nodes if not waiting[node]),
                       key=lambda node: node.name)
        self.order = []
        while ready:
            node = ready.pop()
            self.order.append(node)
            for child in sorted(node.neighbors, key=lambda n: n.name):
                waiting[child] -= 1
                if not waiting[child]:
                    ready.append(child)
        assert len(self.order) == len(nodes)
        self.at = {node: i for i, node in enumerate(self.order)}
        self.up = [0] * len(nodes)            # reflexive ancestor sets
        for i, node in enumerate(self.order):
            code = 1 << i
            for parent in own(dag, node):
                code |= self.up[self.at[parent]]
            self.up[i] = code
        self.cone = [0] * len(nodes)          # reflexive descendant sets
        for i in range(len(nodes) - 1, -1, -1):
            code = 1 << i
            for child in self.order[i].neighbors:
                code |= self.cone[self.at[child]]
            self.cone[i] = code

    def members(self, bits):
        found = set()
        while bits:
            low = bits & -bits
            found.add(self.order[low.bit_length() - 1])
            bits ^= low
        return found


def vocabulary(dag, nodes):
    """The closed code of every node with something below it (itself and
    its ancestors by asserted edges), and for every node whether that is
    the whole order above it: a term's place is computed from its name, so
    a node with a term above it, or a term itself, can be below more than
    its asserted ancestors."""
    closed, whole = {}, {}
    for node in nodes:
        parents = own(dag, node)
        whole[node] = dimensions.split_term(node.name) is None \
            and all(whole[p] for p in parents)
        if node.neighbors:
            closed[node] = frozenset([node]).union(
                *(closed[p] for p in parents))
    return closed, whole


def runs_of(dag, codes):
    """How many runs all the cones take under one numbering of the nodes
    along a spanning tree (SEMANTIC_CODES.md §5): one for each cone, and
    one more for each member that enters it by another parent than its
    primary one, the parent with the most ancestors."""
    runs = len(codes.order)
    for i, node in enumerate(codes.order):
        parents = own(dag, node)
        if not parents:
            continue
        primary = max(parents, key=lambda p: (
            codes.up[codes.at[p]].bit_count(), p.name))
        strict = codes.up[i] & ~(1 << i)
        runs += (strict & ~codes.up[codes.at[primary]]).bit_count()
    return runs


def best(fn, repeat=3):
    times = []
    for _ in range(repeat):
        start = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - start)
    return min(times), out


def shape(dag, codes):
    print("== shape: the shipped vocabulary")
    nodes = codes.order
    edges = sum(len(own(dag, node)) for node in nodes)
    several = sum(1 for node in nodes if len(own(dag, node)) > 1)
    inner = sum(1 for node in nodes if node.neighbors)
    sizes = [codes.up[i].bit_count() - 1 for i in range(len(nodes))]
    pairs = sum(sizes)
    print(f"nodes {len(nodes)}, stored edges {edges}, with something "
          f"below {inner}, with several parents {several} "
          f"({100 * several / len(nodes):.1f}%)")
    print(f"ancestors of a node: mean {pairs / len(nodes):.1f}, median "
          f"{statistics.median(sizes)}, most {max(sizes)}")
    print(f"pairs in the order (the closed code's ones): {pairs}, "
          f"{pairs / edges:.1f} times the stored edges")
    tops = sorted(dag.root.neighbors, key=lambda n: -n.descendant_count)
    print(f"top-level categories: {len(tops)}: " + ", ".join(
        f"{top.name} {top.descendant_count}" for top in tops))


def codes_probe(dag, codes):
    print("== codes: what the closed code costs and what a lookup saves")
    seconds, built = best(lambda: Codes(dag), repeat=1)
    size = sum(sys.getsizeof(bits) for bits in built.up) \
        + sum(sys.getsizeof(bits) for bits in built.cone)
    print(f"both codes for {len(built.order)} nodes built in "
          f"{seconds * 1000:.0f} ms, {size / 1e6:.1f} MB as Python integers")
    wrong = sum(1 for i, node in enumerate(codes.order)
                if codes.cone[i].bit_count() - 1 != node.descendant_count)
    print(f"oracle (I5): cones whose size differs from the stored count: "
          f"{wrong}")
    rng = random.Random(0)
    nodes = codes.order
    pairs = [(rng.choice(nodes), rng.choice(nodes)) for _ in range(20_000)]
    yes = []
    while len(yes) < 20_000:
        node = rng.choice(nodes)
        above = sorted(codes.members(codes.up[codes.at[node]]) - {node},
                       key=lambda n: n.name)
        if above:
            yes.append((node, rng.choice(above)))
    for label, sample in (("random pairs (nearly all no)", pairs),
                          ("a node and one of its ancestors", yes)):
        walk, by_walk = best(lambda: [
            dag._has_ancestors(a, (b,), computed=False) for a, b in sample])
        look, by_code = best(lambda: [
            bool(codes.up[codes.at[a]] >> codes.at[b] & 1) and a is not b
            for a, b in sample])
        assert by_walk == by_code
        print(f"is-below, {label}: walk {walk / len(sample) * 1e6:.2f} µs, "
              f"code {look / len(sample) * 1e6:.2f} µs each")


def trees(dag, codes):
    print("== trees: how far the vocabulary is from a tree "
          "(SEMANTIC_CODES.md §5)")
    members = sum(bits.bit_count() for bits in codes.cone)
    print(f"cone members in all: {members}; as runs of one numbering: "
          f"{runs_of(dag, codes)}; a tree would need {len(codes.order)}")


def tops(dag, codes):
    print("== tops: do the several parents of a node cross top-level "
          "categories?")
    top_bits = 0
    for top in dag.root.neighbors:
        top_bits |= 1 << codes.at[top]
    crossing = within = meets = 0
    spread = {}
    for i, node in enumerate(codes.order):
        count = (codes.up[i] & top_bits).bit_count()
        spread[count] = spread.get(count, 0) + 1
        parents = own(dag, node)
        if len(parents) < 2:
            continue
        if count > 1:
            crossing += 1
        else:
            within += 1
        below_all = ~0
        for parent in parents:
            below_all &= codes.cone[codes.at[parent]]
        if below_all == codes.cone[i]:
            meets += 1
    print("nodes by the number of top-level categories above them: "
          + ", ".join(f"{k}: {v}" for k, v in sorted(spread.items())))
    print(f"nodes with several parents: {crossing + within}; under several "
          f"top-level categories {crossing}, under one {within}")
    print(f"of them, nodes that hold everything below all their parents "
          f"(a meet at this root): {meets}")


def pools_of(dag):
    """The categories an item is filed under, one list per aspect. A node
    filed under a dimension head declares a role, and these are items, so
    the heads are left out."""
    heads = set(dag._heads())
    return [sorted(n.name for n in dag.get_descendants(dag.nodes[name],
                                                       computed=False)
                   if "(" not in n.name and n.name not in heads)
            for name in ASPECTS]


def put(dag):
    print("== put: where filing an item spends its time")
    rng = random.Random(1)
    pools = pools_of(dag)

    def file(start, count):
        for i in range(start, start + count):
            dag.put(f"item-{i}", [rng.choice(pool) for pool in pools])

    file(0, 2000)
    seconds, _ = best(lambda: file(2000, 1000), repeat=1)
    profile = cProfile.Profile()
    profile.enable()
    file(3000, 1000)
    profile.disable()
    spent = {}
    for (path, _line, name), row in pstats.Stats(profile).stats.items():
        if os.path.basename(os.path.dirname(path)) == "ontodag":
            spent[name] = spent.get(name, 0) + row[3]
    whole = spent["put"]
    roles = spent["_reduce_roles_touching"] \
        + spent["_check_role_reference_stays"]
    print(f"a put: {seconds * 1000:.0f} µs; of it is_below "
          f"{100 * spent['is_below'] / whole:.0f}%, the upkeep of roles "
          f"{100 * roles / whole:.0f}% ({len(dag._role_heads())} roles "
          f"declared)")


def filing(dag):
    print(f"== filing: {ITEMS} items, one category from each of "
          f"{', '.join(ASPECTS)}")
    rng = random.Random(1)
    pools = pools_of(dag)
    before = sum(len(own(dag, node)) for node in dag.nodes.values())
    laps = []
    for lap in range(ITEMS // 1000):
        start = time.perf_counter()
        for i in range(lap * 1000, lap * 1000 + 1000):
            dag.put(f"item-{i}", [rng.choice(pool) for pool in pools])
        laps.append(time.perf_counter() - start)
    codes = Codes(dag)
    nodes = codes.order
    edges = sum(len(own(dag, node)) for node in nodes)
    print(f"a put: {laps[0] * 1000:.0f} µs in the first thousand, "
          f"{laps[-1] * 1000:.0f} µs in the last; stored edges "
          f"{before} -> {edges}, nodes {len(nodes)}")
    items = [node for node in nodes if node.name.startswith("item-")]
    pairs = sum(codes.up[codes.at[node]].bit_count() - 1 for node in items)
    print(f"an item's closed code: {pairs / len(items):.1f} ancestors "
          f"against {sum(len(own(dag, n)) for n in items) / len(items):.1f} "
          f"stored parents")

    # One numbering for everything, against closing the vocabulary alone,
    # where an item's place is its parents'.
    members = sum(bits.bit_count() for bits in codes.cone)
    print(f"cone members in all: {members}; as runs of one numbering: "
          f"{runs_of(dag, codes)}")
    closed, whole = vocabulary(dag, nodes)
    print(f"closing the vocabulary alone: {len(closed)} categories, "
          f"{sum(len(code) for code in closed.values())} pairs; the items "
          f"keep their {edges - before} parent edges")
    print(f"categories whose code is the whole order (no term above "
          f"them): {sum(whole[node] for node in closed)} of {len(closed)}")

    # The lattice the store does not build: meets of two categories from
    # different aspects that hold something.
    masks = [codes.cone[codes.at[dag.nodes[name]]] for name in ASPECTS]
    cells = set()
    for node in items:
        above = codes.up[codes.at[node]] & ~(1 << codes.at[node])
        sides = []
        for mask in masks:
            side, bits = [], above & mask
            while bits:
                low = bits & -bits
                side.append(low.bit_length() - 1)
                bits ^= low
            sides.append(side)
        for i in range(len(sides)):
            for j in range(i + 1, len(sides)):
                for a in sides[i]:
                    for b in sides[j]:
                        if a != b:
                            cells.add((a, b) if a < b else (b, a))
    named = {hash(bits) for bits in codes.cone}
    extents = {hash(codes.cone[a] & codes.cone[b]) for a, b in cells}
    possible = sum(len(pools[i]) * len(pools[j])
                   for i in range(len(pools))
                   for j in range(i + 1, len(pools)))
    print(f"pairs of categories from two aspects: {possible} possible, "
          f"{len(cells)} holding something, {len(extents)} different "
          f"answers, {len(extents - named)} of them no stored node's cone")

    # Queries: one broad category from each of two aspects.
    broad = []
    for name in ASPECTS[:2]:
        cone = dag.get_descendants(dag.nodes[name], computed=False)
        broad.append(sorted((n for n in cone if n.descendant_count >= 300
                             and "(" not in n.name),
                            key=lambda n: n.name))
    queries = [(rng.choice(broad[0]), rng.choice(broad[1]))
               for _ in range(200)]

    def planner():
        answers = []
        for a, b in queries:
            dag._memo = None
            answers.append(dag.get([a.name, b.name]))
        return answers

    def closed_vocabulary():
        # Walk the smaller cone as the planner does, then settle each
        # candidate by its parents' codes instead of a climb.
        answers = []
        for a, b in queries:
            small, large = sorted((a, b), key=lambda n: n.descendant_count)
            answers.append({
                c for c in dag.get_descendants(small, computed=False)
                if any(large in closed[p] for p in c.parents)
                or not whole[c] and dag.is_below(c.name, large.name)})
        return answers

    def bitmaps():
        return [codes.cone[codes.at[a]] & codes.cone[codes.at[b]]
                for a, b in queries]

    def counted():
        return [(codes.cone[codes.at[a]] & codes.cone[codes.at[b]])
                .bit_count() for a, b in queries]

    plan, by_plan = best(planner)
    close, by_code = best(closed_vocabulary)
    bits, by_bits = best(bitmaps)
    count, _ = best(counted)
    decode, by_decode = best(lambda: [codes.members(b) for b in by_bits])
    assert by_plan == by_code == by_decode
    sizes = [len(answer) for answer in by_plan]
    smaller = [min(a.descendant_count, b.descendant_count)
               for a, b in queries]
    q = len(queries)
    print(f"{q} two-term queries across two aspects: smaller cone "
          f"{statistics.mean(smaller):.0f} on average, answer "
          f"{statistics.mean(sizes):.0f}")
    print(f"  the planner today                 {plan / q * 1e3:8.3f} ms")
    print(f"  walk, then the vocabulary's codes {close / q * 1e3:8.3f} ms")
    print(f"  cone bit sets, counted            {count / q * 1e3:8.3f} ms")
    print(f"  cone bit sets, listed             "
          f"{(bits + decode) / q * 1e3:8.3f} ms")
    cone_bytes = sum(sys.getsizeof(codes.cone[codes.at[n]]) for n in closed)
    print(f"  cone bit sets for the {len(closed)} categories: "
          f"{cone_bytes / 1e6:.0f} MB")

    # Browsing: the categories that split an answer, with their counts.
    # A category with no term below it holds, by asserted edges, all it
    # holds: its bit set is its cone, and a count from it is the count.
    terms = 0
    for i, node in enumerate(nodes):
        if dimensions.split_term(node.name) is not None:
            terms |= 1 << i
    settled = {node for node in closed
               if not codes.cone[codes.at[node]] & terms}
    asked = [node for node in broad[0] if node in settled][:40]
    answers = [dag.get([node.name]) for node in asked]
    root = dag.root

    def by_walks():
        return [browse.refinements(dag, answer, sample=0)[0]
                for answer in answers]

    climbed = [0]

    def by_codes():
        # A member with a term above it is climbed as today: its code
        # says yes soundly and cannot say no (the computed order).
        out = []
        climbed[0] = 0
        for answer in answers:
            counts = collections.Counter()
            for item in answer:
                if whole[item]:
                    counts.update(frozenset().union(
                        *(closed[p] for p in item.parents)))
                else:
                    climbed[0] += 1
                    counts.update(dag.get_ancestors(item.name))
            del counts[root]
            out.append(sorted(((node.name, n) for node, n in counts.items()
                               if n < len(answer)),
                              key=lambda pair: (-pair[1], pair[0])))
        return out

    columns = [(node, codes.cone[codes.at[node]] & ~(1 << codes.at[node]))
               for node in closed if node is not root]

    def by_cones():
        out = []
        for node in asked:
            i = codes.at[node]
            answer = codes.cone[i] & ~(1 << i)
            out.append((answer, {column: (answer & cone).bit_count()
                                 for column, cone in columns}))
        return out

    walks, by_walk = best(by_walks, repeat=1)
    looks, by_look = best(by_codes, repeat=1)
    cones, by_cone = best(by_cones, repeat=1)
    assert by_walk == by_look
    for answer, walked, (bits, tallied) in zip(answers, by_walk, by_cone):
        assert codes.members(bits) == answer
        walked = dict(walked)
        for column in settled - {root}:
            n = tallied[column]
            assert walked.get(column.name, n) == n and (
                column.name in walked or n in (0, len(answer)))
    total = sum(len(answer) for answer in answers)
    print(f"refinements of {len(answers)} answers ({total} members): "
          f"climbing {walks / len(answers) * 1e3:.1f} ms an answer, the "
          f"vocabulary's codes {looks / len(answers) * 1e3:.1f} ms "
          f"({climbed[0]} members climbed all the same), cone bit sets "
          f"{cones / len(answers) * 1e3:.1f} ms whatever the answer's size "
          f"({len(settled - {root})} of {len(columns)} categories settled "
          f"by them)")


PROBES = ["shape", "codes", "trees", "tops", "filing", "put"]


def main(argv):
    chosen = argv or PROBES
    unknown = [name for name in chosen if name not in PROBES]
    if unknown:
        raise SystemExit(f"unknown probe {unknown[0]}; one of "
                         + ", ".join(PROBES))
    dag = union()
    codes = Codes(dag)
    if "shape" in chosen:
        shape(dag, codes)
    if "codes" in chosen:
        codes_probe(dag, codes)
    if "trees" in chosen:
        trees(dag, codes)
    if "tops" in chosen:
        tops(dag, codes)
    if "filing" in chosen:
        filing(dag)
    if "put" in chosen:
        put(union())


if __name__ == "__main__":
    main(sys.argv[1:])
