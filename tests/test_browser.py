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
