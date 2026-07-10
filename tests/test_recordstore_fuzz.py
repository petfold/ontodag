"""Model-based fuzz test for recordstore.

Runs long random sequences of put/delete/commit against a plain dict
oracle, then checks after every commit that:
  - contents match the oracle exactly (get, contains, keys)
  - the root equals the root of a store rebuilt from scratch from the
    oracle's content (canonical-root property under arbitrary history)

Key alphabet is chosen adversarially for a radix trie: keys that are
prefixes of one another, shared long prefixes diverging at various
depths, unicode, and single-character keys.
"""

import random
import unittest

from recordstore import MemoryChunkStore, RecordStore


KEY_POOL = (
    ["a", "ab", "abc", "abcd", "abcdef", "abd", "b", "ba", "bab"]
    + ["ns:" + s for s in ("x", "xy", "xyz", "xz", "y")]
    + ["común", "comú", "日本語", "日本", "🐝", "🐝🐝"]
    + [f"k{i:02d}" for i in range(20)]
)


def rebuild_root(content):
    """Root of a fresh store containing exactly `content` (one commit)."""
    rs = RecordStore(MemoryChunkStore())
    for k, v in content.items():
        rs.put(k, v)
    return rs.commit()


class TestFuzzAgainstDictModel(unittest.TestCase):
    SEEDS = range(12)
    OPS_PER_RUN = 400

    def _run(self, seed):
        rng = random.Random(seed)
        rs = RecordStore(MemoryChunkStore())
        model = {}

        for step in range(self.OPS_PER_RUN):
            op = rng.random()
            key = rng.choice(KEY_POOL)
            if op < 0.55:
                value = {"n": rng.randrange(1000), "k": key}
                rs.put(key, value)
                model[key] = value
            elif op < 0.8:
                if rng.random() < 0.5 and model:
                    key = rng.choice(sorted(model))
                try:
                    rs.delete(key)
                    model.pop(key, None)
                except KeyError:
                    self.assertNotIn(key, model,
                                     f"seed={seed} step={step}: store raised "
                                     f"KeyError but model has {key!r}")
            else:
                rs.commit()
                self._check(rs, model, seed, step)

        rs.commit()
        self._check(rs, model, seed, "final")

    def _check(self, rs, model, seed, step):
        ctx = f"seed={seed} step={step}"
        self.assertEqual(list(rs.keys()), sorted(model), ctx)
        for k, v in model.items():
            self.assertEqual(rs.get(k), v, ctx)
        for k in KEY_POOL:
            self.assertEqual(rs.contains(k), k in model, f"{ctx} key={k!r}")
        self.assertEqual(rs.root, rebuild_root(model),
                         f"{ctx}: root differs from canonical rebuild")

    def test_random_histories_match_model_and_stay_canonical(self):
        for seed in self.SEEDS:
            self._run(seed)


if __name__ == "__main__":
    unittest.main()
