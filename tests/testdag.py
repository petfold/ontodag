import os
import unittest
from dag import OntoDAG, OntoDAGVisualizer, Item


class TestOntoDAG(unittest.TestCase):
    def setUp(self):
        self.a = Item('A')
        self.b = Item('B')
        self.c = Item('C')
        self.d = Item('D')
        self.e = Item('E')
        self.f = Item('F')
        self.g = Item('G')
        self.ab = Item('AB')
        self.af = Item('AF')
        self.bc = Item('BC')
        self.cd = Item('CD')
        self.abc = Item('ABC')
        self.abf = Item('ABF')

        self.dag = OntoDAG()
        self.dag.put(self.a, [])
        self.dag.put(self.b, [])
        self.dag.put(self.c, [])
        self.dag.put(self.d, [])
        self.dag.put(self.f, [])
        self.dag.put(self.g, [])
        self.dag.put(self.af, [self.a, self.f])
        self.dag.put(self.ab, [self.a, self.b])
        self.dag.put(self.bc, [self.b, self.c])
        self.dag.put(self.abc, [self.ab, self.bc])
        self.dag.put(self.abf, [self.ab, self.af])
        self.dag.put(self.cd, [self.c, self.d])

    def test_common_subcategories(self):
        query_items = [self.b, self.c]
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['ABC', 'BC'], sorted([item.name for item in common_subcategories]))

    def test_ancestors_of_AF(self):
        ancestors = self.dag.get_ancestors(self.af, {self.dag.root})
        self.assertIsNotNone(ancestors)
        self.assertEqual(['A', 'F'], sorted([item.name for item in ancestors]))

    def test_descendant_count(self):
        descendants = self.dag.get_descendants(self.a)
        self.assertEqual(4, len(descendants))

    def test_descendant_count_after_put(self):
        self.dag.put(self.e, [self.ab, self.cd], optimized=True)
        descendants = self.dag.get_descendants(self.a)
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertEqual(5, len(descendants))

    def test_descendant_count_after_remove(self):
        ancestor_node = self.f
        descendants_before = self.dag.get_descendants(ancestor_node)
        self.assertEqual(2, len(descendants_before))
        self.assertEqual(['ABF', 'AF'], sorted([subcategory.name for subcategory in descendants_before]))

        self.dag.remove(self.af)

        descendants_after = self.dag.get_descendants(ancestor_node)
        self.assertEqual(1, len(descendants_after))
        self.assertEqual(['ABF'], [subcategory.name for subcategory in ancestor_node.neighbors])
        self.assertEqual(['AB', 'ABF'], sorted([subcategory.name for subcategory in self.a.neighbors]))

    def test_visualize(self):
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertTrue(os.path.isfile('ontodag_vis'))
        self.assertTrue(os.path.isfile('ontodag_vis.png'))
        os.remove('ontodag_vis')
        os.remove('ontodag_vis.png')

    def test_put_optimized(self):
        element_set_query = [self.ab, self.cd]
        self.dag.put(self.e, element_set_query, optimized=True)
        query_items = [self.abc, self.cd]
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['E'], [item.name for item in common_subcategories])


if __name__ == '__main__':
    unittest.main()
