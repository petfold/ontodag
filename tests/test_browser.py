"""The browser adapters, driven through fake JavaScript.

What these can and cannot prove: the *logic* of the adapters is exercised
end to end — a real `RecordStore` and a real `EagerOntoDAG` run on top of
them, produce a canonical root, and read it back. What is not exercised is
any actual browser: no Pyodide, no bee-js, no wasm. So these tests catch a
broken adapter, and would not catch a wrong assumption about the platform.

Written that way deliberately rather than skipped, because the adapter is
the part we control and the part that would otherwise rot silently.
"""

import json
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
        # recordstore 0.23 reads an unreachable trie node as unavailable, not
        # absent: the page's BlobUnreachable arrives as RecordUnavailable.
        from recordstore import RecordUnavailable
        _direct, page, retrying = self.readers(unreachable=list(self.blobs))
        with self.assertRaises(RecordUnavailable) as caught:
            until_answered(page, retrying, "get", "c0")
        self.assertIn("not retrievable", str(caught.exception))


class Stage:
    """The page's stage (publish.js `Stage`): `put` computes a blob's
    reference and keeps the bytes until they are uploaded; `get` hands kept
    bytes back. Swarm addressing where swarmfs is installed, as in the page;
    sha256 otherwise, which the logic does not care about."""

    def __init__(self, swarm=None):
        import importlib.util
        if swarm is None:
            swarm = importlib.util.find_spec("swarmfs") is not None
        self.swarm = swarm
        self.kept = {}

    def address(self, data):
        if self.swarm:
            from swarmfs.splitter import content_address
            return content_address(data).hex()
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def put(self, data):
        data = bytes(data)
        ref = self.address(data)
        self.kept[ref] = data
        return ref

    def get(self, ref):
        return self.kept.get(ref)


class Device:
    """One browser with your store open: its stage, and the published blobs
    as its page reads them. `upload()` is the page's upload of everything
    staged; the feed is a root the test passes along."""

    def __init__(self, network, store=None):
        from ontodag.browser import LocalStore
        self.network = network
        self.stage = Stage()
        self.store = store if store is not None else LocalStore()

    def blobs(self):
        from ontodag.browser import StagedBlobs
        return StagedBlobs(self.stage, JsBytesStore(FakePageBee(self.network), bridge))

    def publish(self, feed_root):
        import json
        answer = json.loads(self.store.publish(feed_root or "", self.blobs()))
        self.network.update(self.stage.kept)
        return answer

    def fetch(self, feed_root):
        import json
        return json.loads(self.store.fetch(feed_root, self.blobs()))

    def names(self):
        return sorted(n for n in self.store.dag.nodes if n != "*")


def _built(puts, blobs):
    """The root `odag -f swarm:NAME` commits for the same puts."""
    from recordstore import RecordStore
    from ontodag.eager import EagerOntoDAG
    dag = EagerOntoDAG(RecordStore(blobs))
    for name, supers in puts:
        dag.put(name, supers)
    return dag.commit()


class TestPublishingYourStore(unittest.TestCase):
    """Your own store written to Swarm from the page, as `odag -f
    swarm:NAME` saves it (BROWSER.md §16): the same root for the same
    knowledge, committed as it is onto the root it descends from, folded
    with the feed when the feed moved on."""

    def test_the_root_is_the_one_odag_commits_and_every_blob_was_staged(self):
        import importlib.util
        import tempfile
        from recordstore import DirBytesStore, MemoryBytesStore, RecordStore
        from ontodag import native
        from ontodag.eager import EagerOntoDAG
        network = {}
        device = Device(network)
        for name, supers in FRUIT:
            device.store.put(name, " ".join(supers))
        root = device.publish(None)["root"]
        if importlib.util.find_spec("swarmfs"):
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(root, _built(FRUIT, DirBytesStore(d, addressing="swarm")))
        else:
            self.assertEqual(root, _built(FRUIT, Stage(swarm=False)))
        # Read back from what was uploaded alone, nothing from the page.
        published = MemoryBytesStore()
        published.blobs = dict(network)
        again = EagerOntoDAG(RecordStore.at(root, published))
        self.assertEqual(native.dumps(again), device.store.text())

    def test_an_unmoved_feed_takes_the_store_as_it_is_removals_included(self):
        network = {}
        device = Device(network)
        for name, supers in FRUIT:
            device.store.put(name, " ".join(supers))
        first = device.publish(None)
        device.store.remove("pear")
        second = device.publish(first["root"])
        self.assertFalse(second["merged"])
        self.assertEqual(second["root"], _built([p for p in FRUIT if p[0] != "pear"], Stage()))
        # nothing changed: the same root, and nothing new to upload
        staged = len(device.stage.kept)
        self.assertEqual(device.publish(second["root"])["root"], second["root"])
        self.assertEqual(len(device.stage.kept), staged)

    def test_a_feed_written_elsewhere_is_folded_in(self):
        network = {}
        laptop, phone = Device(network), Device(network)
        laptop.store.put("fruit")
        laptop.store.put("apple", "fruit")
        first = laptop.publish(None)["root"]
        fetched = phone.fetch(first)
        self.assertEqual(fetched["came_in"], ["apple", "fruit"])
        self.assertEqual(phone.store.text(), laptop.store.text())
        phone.store.put("pear", "fruit")
        second = phone.publish(first)
        self.assertFalse(second["merged"])
        laptop.store.put("plum", "fruit")
        third = laptop.publish(second["root"])
        self.assertTrue(third["merged"])
        self.assertEqual(third["came_in"], ["pear"])
        self.assertTrue(third["changed"])           # its file lacks the pear
        self.assertEqual(laptop.names(), ["apple", "fruit", "pear", "plum"])
        union = [("fruit", []), ("apple", ["fruit"]), ("pear", ["fruit"]), ("plum", ["fruit"])]
        self.assertEqual(third["root"], _built(union, Stage()))

    def test_a_removal_comes_back_when_the_feed_still_has_it(self):
        # odag's save folds a moved head the same way: a removal is local
        # (CLAUDE.md, "The core's semantics").
        network = {}
        laptop, phone = Device(network), Device(network)
        for name, supers in FRUIT:
            laptop.store.put(name, " ".join(supers))
        first = laptop.publish(None)["root"]
        phone.fetch(first)
        phone.store.put("kiwi", "fruit")
        second = phone.publish(first)["root"]
        laptop.store.remove("pear")
        laptop.publish(second)
        self.assertIn("pear", laptop.names())
        self.assertIn("kiwi", laptop.names())

    def test_a_store_from_a_file_is_folded_with_the_feed(self):
        from ontodag.browser import LocalStore
        network = {}
        laptop = Device(network)
        laptop.store.put("fruit")
        laptop.store.put("apple", "fruit")
        first = laptop.publish(None)["root"]
        old = LocalStore()
        old.put("fruit")
        old.put("pear", "fruit")
        opened = LocalStore.from_text(old.text(), "old.od")
        later = Device(network, opened).publish(first)
        self.assertTrue(later["merged"])
        self.assertEqual(later["came_in"], ["apple"])
        self.assertEqual(sorted(n for n in opened.dag.nodes if n != "*"), ["apple", "fruit", "pear"])

    def test_fetching_into_a_new_store_gives_the_published_one(self):
        network = {}
        laptop, phone = Device(network), Device(network)
        for name, supers in FRUIT:
            laptop.store.put(name, " ".join(supers))
        root = laptop.publish(None)["root"]
        phone.fetch(root)
        self.assertEqual(phone.store.text(), laptop.store.text())
        self.assertEqual(phone.publish(root)["root"], root)
        self.assertEqual(phone.fetch(root)["came_in"], [])

    def test_an_empty_store_is_not_published(self):
        network = {}
        answer = Device(network).publish(None)
        self.assertIn("empty", answer["error"])
        self.assertEqual(network, {})

    def test_in_retry_mode_nothing_changes_until_every_blob_is_fetched(self):
        import json
        from ontodag.browser import RETRY, LocalStore, StagedBlobs, needing
        network = {}
        laptop = Device(network)
        for name, supers in FRUIT:
            laptop.store.put(name, " ".join(supers))
        root = laptop.publish(None)["root"]
        tools = LocalStore()
        tools.put("tool")
        tools.put("hammer", "tool")
        text = tools.text()
        wanted = Device(dict(network), LocalStore.from_text(text)).publish(root)
        page = RetryPage(network)
        stage = Stage()
        store = LocalStore.from_text(text)
        before = store.text()
        for runs in range(1, 50):
            blobs = StagedBlobs(stage, JsBytesStore(page, RETRY))
            answer = json.loads(needing(store.publish, root, blobs))
            if "need" not in answer:
                break
            self.assertEqual(store.text(), before)    # nothing changed yet
            self.assertEqual(stage.kept, {})          # nothing staged yet
            page.fetch(answer["need"])
        self.assertGreater(runs, 1)
        self.assertEqual(answer["root"], wanted["root"])
        self.assertEqual(answer["came_in"], wanted["came_in"])


CORE_TEXT = ("information '*'\nimage information\nphotograph image physical-object\n"
             "physical-object '*'\nagent '*'\nperson agent\nfriend person\n"
             "signal information\nphone-number signal\n")


class TestTheOrganiser(unittest.TestCase):
    """Your store with vocabularies shown beside it (BROWSER.md §17):
    answers from the composed view, writes to your store alone, a
    vocabulary's category taken as a name only (question 39), contact
    details under about(person) and a class (question 44)."""

    def setUp(self):
        from ontodag import native
        from ontodag.browser import LocalStore, Organiser
        from ontodag.packs import pack_dag
        self.texts = {"prelude": native.dumps(pack_dag("prelude")), "core": CORE_TEXT}
        self.org = Organiser(LocalStore(), self.texts)
        self.org.show(["core"])

    def ask(self, method, *args):
        return json.loads(getattr(self.org, method)(*args))

    def test_showing_a_pack_reads_what_it_presumes(self):
        self.assertEqual(self.ask("show", ["core"]), {"shown": ["core"], "read": ["prelude", "core"]})
        self.assertIn("error", self.ask("show", ["no-such-pack"]))

    def test_a_vocabularys_category_enters_your_store_as_a_name_only(self):
        answer = self.ask("add", "myphoto", "photograph")
        self.assertEqual((answer["taken"], answer["created"]), (["photograph"], []))
        self.assertEqual(sorted(self.org.mine.dag.nodes["photograph"].parents, key=str)[0].name, "*")
        self.assertEqual([p.name for p in self.org.mine.dag.nodes["myphoto"].parents], ["photograph"])

    def test_answers_read_the_view_writes_your_store(self):
        self.ask("add", "myphoto", "photograph")
        self.assertEqual(self.ask("get", "image")["mine"], ["myphoto", "photograph"])
        self.assertNotIn("image", self.org.mine.dag.nodes)
        self.ask("show", [])
        hidden = self.ask("get", "image")
        self.assertTrue("error" in hidden or hidden["count"] == 0, hidden)

    def test_a_made_up_category_is_created_and_said(self):
        answer = self.ask("add", "Rome Trip", '"My Holidays" travel')
        self.assertEqual((answer["put"], answer["created"]), ("rome-trip", ["my-holidays", "travel"]))

    def test_contact_details_go_under_about_and_a_class(self):
        self.ask("add", "alice", "friend person")
        answer = self.ask("add", "+44 7700 900123", "about(alice) phone-number")
        self.assertEqual(answer["put"], "+447700900123")
        self.assertGreater(answer["prelude"], 0)
        self.ask("add", "alice.42", "about(alice) signal-id")
        node = self.ask("node", "alice")
        self.assertEqual(node["about"], [["+447700900123", ["phone-number"]], ["alice.42", ["signal-id"]]])
        self.assertEqual(node["above"], [["friend", "mine"]])
        self.assertEqual(self.ask("get", "friend")["mine"], ["alice"])
        self.assertEqual(self.ask("get", "about(alice) phone-number")["mine"], ["+447700900123"])

    def test_the_view_after_writes_is_the_one_composed_afresh(self):
        from ontodag import native
        from ontodag.browser import Organiser
        self.org.view()
        for item, under in [("myphoto", "photograph"), ("alice", "friend person"),
                            ("+44 7700 900123", "about(alice) phone-number"), ("rome", "")]:
            self.ask("add", item, under)
        fresh = Organiser(self.org.mine, self.texts)
        fresh.show(["core"])
        self.assertEqual(native.dumps(self.org.view()), native.dumps(fresh.view()))

    def test_a_removal_is_composed_again(self):
        self.ask("add", "myphoto", "photograph")
        self.ask("get", "image")
        self.ask("remove", "myphoto")
        self.assertEqual(self.ask("get", "image")["mine"], ["photograph"])

    def test_which_packs_your_store_takes_names_from(self):
        self.ask("add", "myphoto", "photograph")
        self.ask("add", "alice", "about(bob)")
        self.assertEqual(self.ask("uses"), {"packs": ["core"]})

    def test_the_side_list_shows_tops_and_what_has_something_below(self):
        self.ask("add", "rome-2026", "holiday")
        self.ask("add", "img-1", "rome-2026")
        self.ask("add", "taxes", "")
        tree = self.ask("tree")["tree"]
        self.assertEqual(tree, [["holiday", 0, 2], ["rome-2026", 1, 1], ["taxes", 0, 0]])

    def test_suggestions_put_yours_first(self):
        self.ask("add", "photo-album", "")
        names = [s["name"] for s in self.ask("suggest", "photo")["suggestions"]]
        self.assertEqual(names[:2], ["photo-album", "photograph"])


class TestTheOrganisersFiles(unittest.TestCase):
    """Your files in the page (BROWSER.md §17, questions 40 to 46): the page
    lists a folder or single files and hashes them; the organiser says which
    to read, what the folder holds by kind (a layer, never written), files
    what is not yet filed as documents with their contents as versions,
    attaches a recognised edit (with undo), and offers single files as a new
    version of a document of their name."""

    def setUp(self):
        from ontodag import native
        from ontodag.browser import LocalStore, Organiser
        from ontodag.packs import pack_dag
        texts = {"prelude": native.dumps(pack_dag("prelude")), "core": CORE_TEXT}
        self.org = Organiser(LocalStore(), texts)
        self.org.show(["core"])

    def ask(self, method, *args):
        return json.loads(getattr(self.org, method)(*args))

    @staticmethod
    def sha(text):
        import hashlib
        return hashlib.sha256(text.encode()).hexdigest()

    def seen(self, path, text, mtime=1791000000.0):
        return {"path": path, "size": len(text), "mtime": mtime, "sha256": self.sha(text)}

    def look(self, files, name="Holiday", whole=True):
        return self.ask("files_look", json.dumps(files), name, whole)

    def versions(self, doc):
        from ontodag.folders import versions_of
        return versions_of(self.org.mine.dag, doc)

    def test_hidden_and_temporary_files_are_not_read(self):
        listing = [["IMG_1.jpg", 10, 1.0], [".git/config", 5, 1.0], ["notes.md~", 3, 1.0],
                   ["a/b/report.pdf", 7, 1.0]]
        self.assertEqual(self.ask("files_plan", json.dumps(listing)), {"read": [0, 3], "skipped": 2})

    def test_a_folder_is_read_by_kind_and_nothing_is_written(self):
        from ontodag import native
        before = native.dumps(self.org.mine.dag)
        a = self.look([self.seen("IMG_1.jpg", "one"), self.seen("IMG_2.jpg", "two"),
                       self.seen("trip.pdf", "pdf"), self.seen("copy/IMG_1.jpg", "one"),
                       self.seen("misc.xyz", "x"),
                       {"path": "big.mp4", "size": 10 ** 10, "mtime": 1.0, "sha256": None}])
        self.assertEqual((a["name"], a["files"], a["unhashed"], a["filed"]), ("Holiday", 6, 1, 0))
        self.assertEqual(a["kinds"], {"document": 1, "image-file": 3, "other": 1, "video-file": 1})
        unfiled = {u["name"]: u for u in a["unfiled"]}
        self.assertEqual(sorted(unfiled), ["IMG_1.jpg", "IMG_2.jpg", "misc.xyz", "trip.pdf"])
        self.assertEqual(unfiled["IMG_1.jpg"]["paths"], ["IMG_1.jpg", "copy/IMG_1.jpg"])   # copies are one
        self.assertEqual(unfiled["IMG_1.jpg"]["kind"], "image-file")
        self.assertEqual((a["attached"], a["changed"]), ([], False))
        self.assertEqual(native.dumps(self.org.mine.dag), before)

    def test_filing_puts_documents_under_categories_with_their_versions(self):
        a = self.look([self.seen("IMG_1.jpg", "one"), self.seen("trip.pdf", "pdf")])
        f = self.ask("files_file", json.dumps([u["sha256"] for u in a["unfiled"]]),
                     "holiday photograph", "{}")
        self.assertEqual(sorted(x["document"] for x in f["filed"]), ["IMG_1.jpg", "trip.pdf"])
        self.assertEqual((f["taken"], f["created"], f["changed"]), (["photograph"], ["holiday"], True))
        self.assertTrue(self.org.mine.changed)
        self.assertEqual(self.versions("IMG_1.jpg"), ["sha256:" + self.sha("one")])
        self.assertEqual(sorted(p.name for p in self.org.mine.dag.nodes["IMG_1.jpg"].parents),
                         ["holiday", "photograph"])
        found = self.ask("get", "holiday image")["mine"]
        self.assertTrue({"IMG_1.jpg", "trip.pdf"} <= set(found), found)
        again = self.look([self.seen("IMG_1.jpg", "one"), self.seen("trip.pdf", "pdf")])
        self.assertEqual((again["filed"], again["unfiled"]), (2, []))

    def test_only_what_was_looked_at_and_read_can_be_filed(self):
        a = self.look([{"path": "big.mp4", "size": 10 ** 10, "mtime": 1.0, "sha256": None}])
        self.assertEqual(a["unfiled"], [])
        self.assertIn("error", self.ask("files_file", json.dumps([self.sha("never seen")]), "", "{}"))

    def test_an_edit_is_attached_as_a_new_version_and_can_be_undone(self):
        a = self.look([self.seen("notes.md", "v1")])
        self.ask("files_file", json.dumps([a["unfiled"][0]["sha256"]]), "notes", "{}")
        b = self.look([self.seen("notes.md", "v2", mtime=1791000500.0)])
        self.assertEqual([(x["path"], x["document"]) for x in b["attached"]], [("notes.md", "notes.md")])
        self.assertEqual((b["unfiled"], len(self.versions("notes.md"))), ([], 2))
        undone = self.ask("files_undo", json.dumps([b["attached"][0]["version"]]))
        self.assertEqual(undone["undone"], [b["attached"][0]["version"]])
        self.assertEqual(self.versions("notes.md"), ["sha256:" + self.sha("v1")])
        # Undone, it is not attached again; it waits in the work list instead.
        c = self.look([self.seen("notes.md", "v2", mtime=1791000500.0)])
        self.assertEqual(c["attached"], [])
        self.assertEqual([(u["name"], u["like"]) for u in c["unfiled"]], [("notes.md", ["notes.md"])])

    def test_single_files_are_offered_as_a_new_version_of_a_document_of_their_name(self):
        a = self.look([self.seen("notes.md", "v1")])
        self.ask("files_file", json.dumps([a["unfiled"][0]["sha256"]]), "notes", "{}")
        b = self.look([self.seen("notes.md", "v2")], "", False)
        self.assertEqual((b["attached"], b["unfiled"][0]["like"]), ([], ["notes.md"]))
        sha = b["unfiled"][0]["sha256"]
        f = self.ask("files_file", json.dumps([sha]), "", json.dumps({sha: "notes.md"}))
        self.assertEqual((f["filed"][0]["document"], f["filed"][0]["made"]), ("notes.md", False))
        self.assertEqual(len(self.versions("notes.md")), 2)
