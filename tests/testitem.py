import unittest
from ontodag.dag import Item


class TestItem(unittest.TestCase):
    def test_distinct_instances(self):
        item1 = Item("A")
        item2 = Item("A")
        self.assertIsNot(item1, item2)

    def test_different_instances(self):
        item1 = Item("A")
        item2 = Item("B")
        self.assertIsNot(item1, item2)

    def test_instance_attributes(self):
        item = Item("A")
        self.assertEqual(item.name, "A")
        self.assertEqual(item.neighbors, set())
        self.assertEqual(item.descendant_count, 0)

    def test_equality(self):
        item1 = Item("A")
        item2 = Item("A")
        item3 = Item("B")
        self.assertEqual(item1, item2)
        self.assertNotEqual(item1, item3)

    def test_hash(self):
        item1 = Item("A")
        item2 = Item("A")
        item3 = Item("B")
        self.assertEqual(hash(item1), hash(item2))
        self.assertNotEqual(hash(item1), hash(item3))

    def test_repr(self):
        item = Item("A")
        self.assertEqual(repr(item), "Item(A, [])")

    def test_metadata_defaults_empty_and_is_copied(self):
        self.assertEqual(Item("A").metadata, {})
        source = {"label": "a.txt"}
        item = Item("A", metadata=source)
        source["label"] = "changed"
        self.assertEqual(item.metadata, {"label": "a.txt"})

    def test_metadata_never_affects_identity(self):
        plain = Item("A")
        tagged = Item("A", metadata={"label": "a.txt"})
        self.assertEqual(plain, tagged)
        self.assertEqual(hash(plain), hash(tagged))

    def test_to_dict_includes_metadata_only_when_present(self):
        self.assertNotIn("metadata", Item("A").to_dict())
        item = Item("A", metadata={"label": "a.txt"})
        self.assertEqual(item.to_dict()["metadata"], {"label": "a.txt"})


if __name__ == '__main__':
    unittest.main()
