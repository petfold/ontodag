"""Integration test: recordstore against a live Bee node.

Run a dev-mode node (in-memory, no blockchain, instant stamps):

    bee dev --api-addr=127.0.0.1:1633

Then:

    BEE_API=http://127.0.0.1:1633 python3 -m pytest test_recordstore_bee.py -v

A postage batch is created automatically unless BEE_BATCH is set.
Skipped entirely when BEE_API is not set, so it is safe in CI.
"""

import os
import time
import unittest

BEE_API = os.environ.get("BEE_API")


@unittest.skipUnless(BEE_API, "set BEE_API to run Bee integration tests")
class TestAgainstLiveBee(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import requests
        cls.batch = os.environ.get("BEE_BATCH")
        if not cls.batch:
            r = requests.post(f"{BEE_API}/stamps/100000000/20", timeout=60)
            r.raise_for_status()
            cls.batch = r.json()["batchID"]
            deadline = time.time() + 120
            while time.time() < deadline:  # wait until the batch is usable
                s = requests.get(f"{BEE_API}/stamps/{cls.batch}", timeout=30)
                if s.ok and s.json().get("usable"):
                    break
                time.sleep(2)
            else:
                raise RuntimeError("postage batch never became usable")

    def _store(self):
        from recordstore import BeeChunkStore
        return BeeChunkStore(BEE_API, self.batch)

    def test_roundtrip_through_bee(self):
        from recordstore import RecordStore
        chunks = self._store()
        rs = RecordStore(chunks)
        rec = {"up": ["vehicle"], "down": ["tesla"], "count": 1}
        rs.put("car", rec)
        rs.put("ns:日本語", {"unicode": True})
        root = rs.commit()
        again = RecordStore.at(root, chunks)
        self.assertEqual(again.get("car"), rec)
        self.assertEqual(again.get("ns:日本語"), {"unicode": True})
        self.assertEqual(list(again.keys()), ["car", "ns:日本語"])

    def test_canonical_root_on_bee_refs(self):
        """Same content, different insertion order => same Bee root."""
        from recordstore import RecordStore
        content = {f"k{i:02d}": {"n": i} for i in range(25)}

        def build(order):
            rs = RecordStore(self._store())
            for k in order:
                rs.put(k, content[k])
                rs.commit()
            return rs.root

        keys = sorted(content)
        self.assertEqual(build(keys), build(list(reversed(keys))))

    def test_large_record_uses_bee_splitter(self):
        """A record far exceeding one 4 KB chunk still yields one reference."""
        from recordstore import RecordStore
        chunks = self._store()
        rs = RecordStore(chunks)
        big = {"blob": "x" * 50_000, "edges": [f"e{i}" for i in range(500)]}
        rs.put("hub", big)
        root = rs.commit()
        self.assertEqual(RecordStore.at(root, chunks).get("hub"), big)

    def test_snapshot_isolation_over_bee(self):
        from recordstore import RecordStore
        chunks = self._store()
        writer = RecordStore(chunks)
        writer.put("a", {"v": 1})
        root1 = writer.commit()
        reader = RecordStore.at(root1, chunks)
        writer.put("a", {"v": 2})
        writer.commit()
        self.assertEqual(reader.get("a"), {"v": 1})


if __name__ == "__main__":
    unittest.main()
