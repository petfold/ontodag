"""Chunks a store's blobs take on Swarm, plain and erasure-coded, from the
blob sizes and Bee 2.8.2's tables (pkg/file/redundancy/level.go): data
chunks, intermediate chunks, parities per intermediate chunk, and the root's
dispersed replicas (2, 4, 8, 16 for levels 1-4), which the node writes for
every upload at a level above 0, one chunk included (measured)."""
import math, os, sys
TABLES = {  # (shard thresholds, parities), as Bee lists them
    1: ([95, 69, 47, 29, 15, 6, 2, 1], [9, 8, 7, 6, 5, 4, 3, 2]),
    2: ([105, 96, 87, 78, 70, 62, 54, 47, 40, 33, 27, 21, 16, 11, 7, 4, 2, 1],
        [21, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4]),
}
REPLICAS = {0: 0, 1: 2, 2: 4}

def parities(level, shards):
    if level == 0: return 0
    th, ps = TABLES[level]
    for t, p in zip(th, ps):
        if shards >= t: return p
    return 0

def max_shards(level):
    return 128 if level == 0 else 128 - parities(level, 128 - TABLES[level][1][0])

def chunks(size, level):
    n = max(1, math.ceil(size / 4096))
    if n == 1:
        return 1 + REPLICAS[level]
    total, m = n, max_shards(level)
    while n > 1:
        groups = math.ceil(n / m)
        for g in range(groups):
            s = min(m, n - g * m)
            total += parities(level, s) + 1     # its parities and the intermediate chunk
        n = groups
    return total + REPLICAS[level]

for d in sys.argv[1:]:
    sizes = [os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(d) for f in fs]
    small = sum(1 for s in sizes if s <= 4096)
    line = [f"{os.path.basename(os.path.dirname(d.rstrip('/')))}: {len(sizes)} blobs, {small} of them one chunk, {sum(sizes)/1e6:.1f} MB"]
    base = sum(chunks(s, 0) for s in sizes)
    for lv in (0, 1, 2):
        c = sum(chunks(s, lv) for s in sizes)
        line.append(f"level {lv}: {c} chunks ({c/base:.2f}x)")
    print("; ".join(line))
