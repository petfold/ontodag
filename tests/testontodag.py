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


if __name__ == "__main__":
    unittest.main()
