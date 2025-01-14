import unittest
from ontodag import Item


class TestItem(unittest.TestCase):
    def setUp(self):
        self.item = Item("TestItem")

    def test_initial_counter(self):
        self.assertEqual(self.item.counter, 0)

    def test_increase_counter(self):
        self.item.increase_counter()
        self.assertEqual(self.item.counter, 1)
        self.item.increase_counter()
        self.assertEqual(self.item.counter, 2)

    def test_decrease_counter(self):
        self.item.increase_counter()
        self.item.increase_counter()
        self.item.decrease_counter()
        self.assertEqual(self.item.counter, 1)
        self.item.decrease_counter()
        self.assertEqual(self.item.counter, 0)

    def test_counter_not_below_zero(self):
        self.item.counter = 0
        self.item.decrease_counter()
        self.assertEqual(self.item.counter, 0)

    def test_add_subcategory(self):
        subcategory = Item("SubItem")
        self.item.add_subcategory(subcategory)
        self.assertIn(subcategory, self.item.subcategories)

    def test_repr(self):
        self.assertEqual(repr(self.item), "Item(TestItem)")


if __name__ == "__main__":
    unittest.main()
