"""The browser adapters, driven through fake JavaScript.

What these can and cannot prove: the *logic* of the adapters is exercised
end to end — a real `RecordStore` and a real `EagerOntoDAG` run on top of
them, produce a canonical root, and read it back. What is not exercised is
any actual browser: no Pyodide, no bee-js, no wasm. So these tests catch a
broken adapter, and would not catch a wrong assumption about the platform.

Written that way deliberately rather than skipped, because the adapter is
the part we control and the part that would otherwise rot silently.
"""

import unittest

from ontodag.browser import JsBytesStore, JsFeedPointer, LocalStorageBytesStore


class FakePromise:
    """What a JS async call hands back. Deliberately *not* a value: the whole
    difficulty being modelled is that the result is not available yet."""

    def __init__(self, value):
        self.value = value


def bridge(promise):
    """Stand-in for `pyodide.ffi.run_sync` / an Atomics.wait worker hop."""
    if isinstance(promise, FakePromise):
        return promise.value
    raise AssertionError("adapter did not go through the async boundary")


class FakeBee:
    """A Bee client with bee-js's shape: async, refs as strings."""

    def __init__(self):
        self.blobs = {}
        self.uploads = 0

    def upload(self, data):
        import hashlib
        raw = bytes(data)
        ref = hashlib.sha256(raw).hexdigest()
        self.blobs[ref] = raw
        self.uploads += 1
        return FakePromise(ref)

    def download(self, ref):
        return FakePromise(self.blobs[str(ref)])


class FakeFeed:
    def __init__(self):
        self.ref = None

    def read(self):
        return FakePromise(self.ref)

    def write(self, ref):
        self.ref = str(ref)
        return FakePromise(None)


class FakeLocalStorage(dict):
    def setItem(self, key, value):
        self[key] = value

    def getItem(self, key):
        return self.get(key)


class TestJsBytesStore(unittest.TestCase):
    def test_round_trip_through_the_async_boundary(self):
        bee = FakeBee()
        store = JsBytesStore(bee, bridge)
        ref = store.put(b"hello")
        self.assertEqual(store.get(ref), b"hello")
        self.assertEqual(bee.uploads, 1)

    def test_a_reference_object_is_accepted_as_well_as_a_string(self):
        # bee-js returns a Reference object in some versions; it stringifies.
        class Ref:
            def __init__(self, hex):
                self._hex = hex

            def __str__(self):
                return self._hex

        bee = FakeBee()
        store = JsBytesStore(bee, bridge)
        raw_ref = store.put(b"payload")
        self.assertEqual(store.get(Ref(raw_ref)), b"payload")

    def test_a_js_typed_array_converts(self):
        class TypedArray:
            def __init__(self, data):
                self._data = data

            def to_py(self):
                return self._data

        class Bee(FakeBee):
            def download(self, ref):
                return FakePromise(TypedArray(self.blobs[str(ref)]))

        store = JsBytesStore(Bee(), bridge)
        self.assertEqual(store.get(store.put(b"abc")), b"abc")


class TestJsFeedPointer(unittest.TestCase):
    def test_absent_then_set_then_read(self):
        pointer = JsFeedPointer(FakeFeed(), bridge)
        self.assertIsNone(pointer.get())
        pointer.set("deadbeef")
        self.assertEqual(pointer.get(), "deadbeef")


class TestLocalStorageBytesStore(unittest.TestCase):
    def test_round_trip(self):
        storage = FakeLocalStorage()
        store = LocalStorageBytesStore(storage)
        ref = store.put(b"\x00\xff binary")
        self.assertEqual(store.get(ref), b"\x00\xff binary")

    def test_a_missing_blob_is_a_keyerror_not_a_none(self):
        with self.assertRaises(KeyError):
            LocalStorageBytesStore(FakeLocalStorage()).get("nope")

    def test_it_is_content_addressed_like_the_others(self):
        store = LocalStorageBytesStore(FakeLocalStorage())
        self.assertEqual(store.put(b"same"), store.put(b"same"))


class TestAWholeDagOnTopOfThem(unittest.TestCase):
    """The point of the exercise: OntoDAG does not know or care."""

    def _store(self, bytes_store, pointer):
        recordstore = __import__("recordstore")
        return recordstore.RecordStore(bytes_store, pointer=pointer)

    def test_a_dag_lives_on_a_javascript_backed_store(self):
        from ontodag.eager import EagerOntoDAG
        bee, feed = FakeBee(), FakeFeed()
        store = self._store(JsBytesStore(bee, bridge),
                            JsFeedPointer(feed, bridge))
        dag = EagerOntoDAG(store)
        dag.put("Travel", [])
        dag.put("Japan", ["Travel"])
        dag.put("doc", ["Japan"])
        root = dag.commit()

        # It reads back in a fresh instance from the feed alone — the
        # browser equivalent of the scorched-earth rehydration test.
        reopened = EagerOntoDAG(
            self._store(JsBytesStore(bee, bridge),
                        JsFeedPointer(feed, bridge)))
        self.assertEqual(
            {i.name for i in reopened.get(["Travel"])}, {"Japan", "doc"})
        self.assertEqual(reopened.store.root, root)

    def test_the_root_is_the_same_one_a_laptop_would_compute(self):
        # The property that makes a browser a peer rather than a silo: the
        # same knowledge must produce the same root as an on-disk store, or
        # nothing can be shared, compared or verified across the two.
        from recordstore import MemoryBytesStore, MemoryPointer, RecordStore
        from ontodag.eager import EagerOntoDAG

        def build(store):
            dag = EagerOntoDAG(store)
            dag.put("Travel", [])
            dag.put("Japan", ["Travel"])
            dag.put("doc", ["Japan"])
            return dag.commit()

        in_browser = build(RecordStore(JsBytesStore(FakeBee(), bridge),
                                       pointer=JsFeedPointer(FakeFeed(),
                                                             bridge)))
        on_disk = build(RecordStore(MemoryBytesStore(),
                                    pointer=MemoryPointer()))
        self.assertEqual(in_browser, on_disk)


if __name__ == "__main__":
    unittest.main()


class FakePageBee(FakeBee):
    """The read-only page's JS store (demo/freedom/swarm.js BlobStore):
    `download`, `downloadMany`, and a missing blob is a rejection."""

    def __init__(self, blobs=None, many=True):
        super().__init__()
        self.blobs = dict(blobs or {})
        self.calls = 0
        if not many:
            self.downloadMany = None

    def download(self, ref):
        self.calls += 1
        if str(ref) not in self.blobs:
            raise RuntimeError(f"chunk {ref} is not retrievable")   # a rejected promise
        return FakePromise(self.blobs[str(ref)])

    def downloadMany(self, refs):
        self.calls += 1
        missing = [r for r in refs if r not in self.blobs]
        if missing:
            raise RuntimeError(f"chunk {missing[0]} is not retrievable")
        return FakePromise([self.blobs[r] for r in refs])


def _published(puts):
    from recordstore import MemoryBytesStore, RecordStore
    from ontodag.eager import EagerOntoDAG
    blobs = MemoryBytesStore()
    dag = EagerOntoDAG(RecordStore(blobs))
    for name, supers in puts:
        dag.put(name, supers)
    return dag.commit(), blobs


FRUIT = [("food", []), ("fruit", ["food"]), ("apple", ["fruit"]),
         ("pear", ["fruit"]), ("bread", ["food"]), ("tool", [])]


class TestTheReadOnlyPage(unittest.TestCase):
    """What demo/freedom's page runs: a published store read lazily
    through the page's JavaScript."""

    def setUp(self):
        self.root, blobs = _published(FRUIT)
        self.blobs = blobs.blobs

    def test_get_many_is_one_call_when_the_page_offers_it(self):
        js = FakePageBee(self.blobs)
        refs = list(self.blobs)[:4]
        got = JsBytesStore(js, bridge).get_many(refs)
        self.assertEqual(got, {r: self.blobs[r] for r in refs})
        self.assertEqual(js.calls, 1)
        one_by_one = FakePageBee(self.blobs, many=False)
        JsBytesStore(one_by_one, bridge).get_many(refs)
        self.assertEqual(one_by_one.calls, 4)

    def test_an_unreachable_blob_is_an_error_never_absence(self):
        from ontodag.browser import BlobUnreachable
        js = FakePageBee({})
        with self.assertRaises(BlobUnreachable) as caught:
            JsBytesStore(js, bridge).get("ab" * 32)
        self.assertNotIsInstance(caught.exception, KeyError)
        # a lazy reader over a store whose blobs are gone fails loudly
        from ontodag.browser import open_published
        dag = open_published(self.root, FakePageBee({}), bridge=bridge)
        with self.assertRaises(Exception) as failed:
            dag.get(["fruit"])
        self.assertNotIsInstance(failed.exception, KeyError)

    def test_the_page_reader_answers_as_the_store_does(self):
        import json
        from ontodag.browser import PageReader, open_published
        reader = PageReader(open_published(self.root, FakePageBee(self.blobs), bridge=bridge))
        top = json.loads(reader.node())
        self.assertTrue(top["top"])
        self.assertEqual([n for n, _ in top["below"]], ["food", "tool"])
        fruit = json.loads(reader.node("fruit"))
        self.assertEqual(fruit["above"], ["food"])
        self.assertEqual(fruit["below"], [["apple", 0], ["pear", 0]])
        self.assertEqual(fruit["count"], 2)
        food = json.loads(reader.node("food"))
        self.assertEqual(dict(food["below"])["fruit"], 2)
        self.assertFalse(json.loads(reader.node("durian"))["found"])
        got = json.loads(reader.get("food"))
        self.assertEqual(got["names"], ["apple", "bread", "fruit", "pear"])
        self.assertTrue(json.loads(reader.below("apple", "food"))["below"])
        self.assertFalse(json.loads(reader.below("apple", "tool"))["below"])
        self.assertGreater(got["records"], 0)

    def test_a_published_cone_index_answers_a_broad_category_in_one_read(self):
        import json
        from recordstore import MemoryBytesStore, RecordStore
        from ontodag.browser import PageReader, open_published
        from ontodag.cones import build_index
        from ontodag.eager import EagerOntoDAG
        puts = [("thing", [])] + [(f"t{i}", ["thing"]) for i in range(40)] + \
               [(f"t{i}.{j}", [f"t{i}"]) for i in range(40) for j in range(3)]
        blobs = MemoryBytesStore()
        dag = EagerOntoDAG(RecordStore(blobs))
        for name, supers in puts:
            dag.put(name, supers)
        root = dag.commit()
        index_root = build_index(dag, RecordStore(blobs), root, threshold=50)
        stale_root = build_index(dag, RecordStore(blobs), "another-root", threshold=50)
        js = FakePageBee(blobs.blobs)

        def get(index):
            reader = PageReader(open_published(root, js, bridge=bridge, index_root=index))
            return json.loads(reader.get("thing"))
        walked, indexed = get(None), get(index_root)
        self.assertEqual((walked["count"], walked["names"]), (indexed["count"], indexed["names"]))
        self.assertEqual(walked["count"], 160)
        self.assertGreater(walked["records"], 150)
        self.assertLess(indexed["records"], 10)
        # an index for another root is ignored, never trusted: the reader walks
        stale = get(stale_root)
        self.assertEqual(stale["names"], walked["names"])
        self.assertGreater(stale["records"], 150)
        # an index the page cannot fetch is a cache miss, not a failure
        unreachable = get("ab" * 32)
        self.assertEqual(unreachable["names"], walked["names"])


class TestTheLocalStore(unittest.TestCase):
    """The page's own store, kept in a local `.od` file (BROWSER.md §14):
    the same text `odag` reads and writes, and the CLI's rules for writes."""

    def answer(self, text):
        import json
        return json.loads(text)

    def test_a_saved_store_is_the_native_format_both_ways(self):
        from ontodag import native
        from ontodag.browser import LocalStore
        store = LocalStore(name="mine.od")
        store.put("fruit")
        store.put("apple", "fruit")
        text = store.text()
        self.assertEqual(text, native.dumps(native.loads(text)))
        again = LocalStore.from_text(text, "mine.od")
        self.assertEqual(self.answer(again.get("fruit"))["names"], ["apple"])
        self.assertEqual(native.dumps(again.dag), text)

    def test_changed_until_saved(self):
        from ontodag.browser import LocalStore
        store = LocalStore()
        self.assertFalse(self.answer(store.summary())["changed"])
        self.assertTrue(self.answer(store.put("fruit"))["changed"])
        store.text()   # a save that failed or was cancelled
        self.assertTrue(self.answer(store.summary())["changed"])
        self.assertEqual(self.answer(store.saved("mine.od"))["name"], "mine.od")
        self.assertFalse(self.answer(store.summary())["changed"])

    def test_an_unknown_parent_is_named_and_nothing_changes(self):
        from ontodag.browser import LocalStore
        store = LocalStore()
        store.put("fruit")
        before = sorted(store.dag.nodes)
        answer = self.answer(store.put("pear", "fruit orchard"))
        self.assertIn("orchard", answer["error"])
        self.assertNotIn("fruit,", answer["error"])
        self.assertEqual(sorted(store.dag.nodes), before)

    def test_remove_contracts_as_odag_remove_does(self):
        from ontodag.browser import LocalStore
        store = LocalStore()
        store.put("food")
        store.put("fruit", "food")
        store.put("apple", "fruit")
        self.assertEqual(self.answer(store.remove("fruit"))["removed"], ["fruit"])
        self.assertEqual(self.answer(store.get("food"))["names"], ["apple"])
        self.assertIn("error", self.answer(store.remove("durian")))

    def test_typed_values_and_relative_times_need_the_prelude_and_the_clock(self):
        from ontodag.browser import LocalStore
        # 2026-10-12 12:00 UTC
        store = LocalStore(now=1791806400)
        self.assertGreater(self.answer(store.prelude())["added"], 0)
        answer = self.answer(store.put("harvest", "'time(today)'"))
        self.assertEqual(answer["under"], ["time(2026-10-12)"])
        self.assertIn("harvest", self.answer(store.get("'time(2026-10)'"))["names"])


class RetryPage:
    """The page in retry mode (demo/freedom/swarm.js BlobStore): `cached`
    answers synchronously from what was fetched (None if not yet; a throw
    if fetching it failed), and `fetch` is the page's await between runs."""

    def __init__(self, blobs, unreachable=()):
        self.blobs = dict(blobs)
        self.held = {}
        self.unreachable = set(unreachable)
        self.fetches = 0

    def cached(self, ref):
        value = self.held.get(str(ref))
        if isinstance(value, Exception):
            raise value
        return value

    def fetch(self, refs):
        self.fetches += 1
        for r in refs:
            if r in self.unreachable or r not in self.blobs:
                self.held[r] = RuntimeError(f"chunk {r} is not retrievable")
            else:
                self.held[r] = self.blobs[r]


def until_answered(page, retrying, method, *args, limit=50):
    """What app.js's call() does in retry mode: run, fetch what was needed,
    run again; the answer and how many runs it took."""
    import json
    for runs in range(1, limit + 1):
        answer = json.loads(retrying.call(method, *args))
        if "need" not in answer:
            return answer, runs
        page.fetch(answer["need"])
    raise AssertionError(f"{method}{args} still needed blobs after {limit} runs")


class TestRetryMode(unittest.TestCase):
    """Where JSPI cannot suspend Python (Pyodide on iOS), the page runs each
    call again after fetching what it lacked (BROWSER.md §15); the answers
    must be exactly those of the waiting bridge."""

    def setUp(self):
        import random
        rng = random.Random(7)
        puts = [(f"c{i}", sorted({f"c{j}" for j in rng.sample(range(i), min(i, rng.choice([1, 1, 2, 3])))}))
                for i in range(60)]
        self.puts = puts
        self.root, blobs = _published(puts)
        self.blobs = blobs.blobs

    def readers(self, **kwargs):
        from ontodag.browser import RETRY, PageReader, RetryingPage, open_published
        direct = PageReader(open_published(self.root, FakePageBee(self.blobs), bridge=bridge))
        page = RetryPage(self.blobs, **kwargs)
        retrying = RetryingPage(lambda: PageReader(open_published(self.root, page, bridge=RETRY)))
        return direct, page, retrying

    def test_every_answer_equals_the_waiting_bridge(self):
        import json
        import random
        direct, page, retrying = self.readers()
        names = [n for n, _ in self.puts]
        rng = random.Random(11)
        calls = [("node", n) for n in names[::5]] + [("node", "missing-name")]
        calls += [("get", f"{a} {b}") for a, b in (rng.sample(names, 2) for _ in range(12))]
        calls += [("below", *rng.sample(names, 2)) for _ in range(12)]
        for method, *args in calls:
            got, runs = until_answered(page, retrying, method, *args)
            want = json.loads(getattr(direct, method)(*args))
            for counts in ("records", "round_trips"):
                got.pop(counts), want.pop(counts)
            self.assertEqual(got, want, (method, args))

    def test_round_trips_are_the_waiting_bridges_plus_one(self):
        from ontodag.browser import PageReader, open_published
        for query in ("c0", "c5", "c30"):
            waiting = FakePageBee(self.blobs)
            PageReader(open_published(self.root, waiting, bridge=bridge)).get(query)
            _direct, page, retrying = self.readers()
            _answer, runs = until_answered(page, retrying, "get", query, limit=1000)
            self.assertEqual(page.fetches, runs - 1)
            self.assertLessEqual(page.fetches, waiting.calls, query)
        # asked again, everything is held: one run, no fetch
        _answer, again = until_answered(page, retrying, "get", "c30")
        self.assertEqual(again, 1)

    def test_a_blob_that_could_not_be_fetched_is_an_error(self):
        from ontodag.browser import BlobUnreachable
        _direct, page, retrying = self.readers(unreachable=list(self.blobs))
        with self.assertRaises(BlobUnreachable):
            until_answered(page, retrying, "get", "c0")
