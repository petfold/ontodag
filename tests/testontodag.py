import unittest

from ontodag import OntoDAG


class TestOntoDAG(unittest.TestCase):
    def setUp(self):
        self.ontodag = OntoDAG()
        self.ontodag.put("Animal", [])
        self.ontodag.put("Mammal", ["Animal"])
        self.ontodag.put("Bird", ["Animal"])
        self.ontodag.put("Dog", ["Mammal"])
        self.ontodag.put("Cat", ["Mammal"])
        self.ontodag.put("Parrot", ["Bird"])
        self.ontodag.put("Has-colour", [])
        self.ontodag.put("Black", ["Has-colour"])
        self.ontodag.put("White", ["Has-colour"])
        self.ontodag.put("Green", ["Has-colour"])
        self.ontodag.put("Black Dog", ["Dog", "Black"])
        self.ontodag.put("Black Cat", ["Cat", "Black"])
        self.ontodag.put("Green Parrot", ["Parrot", "Green"])

    def test_get_subcategories(self):
        result = self.ontodag.get({"Mammal", "Black"})
        expected = {"Black Dog", "Black Cat"}
        self.assertEqual(result, expected)

    def test_get_no_subcategories(self):
        result = self.ontodag.get({"Bird", "Black"})
        expected = set()
        self.assertEqual(result, expected)

    def test_get_single_category(self):
        result = self.ontodag.get({"Mammal"})
        expected = {"Dog", "Cat", "Black Dog", "Black Cat"}
        self.assertEqual(result, expected)

    def test_get_nonexistent_category(self):
        with self.assertRaises(ValueError):
            self.ontodag.get({"Nonexistent"})

    def test_put_nonexistent_supercategory(self):
        with self.assertRaises(ValueError):
            self.ontodag.put("NewItem", ["Nonexistent"])

    def test_remove_existing_item(self):
        self.ontodag.remove("Black Dog")
        result = self.ontodag.get({"Mammal", "Black"})
        expected = {"Black Cat"}
        self.assertEqual(result, expected)

    def test_remove_nonexistent_item(self):
        with self.assertRaises(ValueError):
            self.ontodag.remove("Nonexistent")

    def test_remove_and_check_counters(self):
        self.ontodag.remove("Black Dog")
        self.assertEqual(self.ontodag.items["Dog"].counter, 0)
        self.assertEqual(self.ontodag.items["Black"].counter, 1)
        self.assertEqual(self.ontodag.items["Mammal"].counter, 3)
        self.assertEqual(self.ontodag.items["Has-colour"].counter, 5)

    def test_remove_and_check_subcategories(self):
        self.ontodag.remove("Black Dog")
        result = self.ontodag.get({"Dog"})
        expected = set()
        self.assertEqual(result, expected)

    def test_add_root_item(self):
        root_item = self.ontodag.get_root()
        self.assertIn(root_item.name, self.ontodag.items)
        self.assertEqual(self.ontodag.items[root_item.name].name, root_item.name)
        self.assertEqual(self.ontodag.items[root_item.name].counter, len(self.ontodag.items) - 1)


if __name__ == "__main__":
    unittest.main()
