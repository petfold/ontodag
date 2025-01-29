import unittest
from dag import Item


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


if __name__ == '__main__':
    unittest.main()
