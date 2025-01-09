import os
import unittest
from dag import OntoDAG, OntoDAGVisualizer


class TestOntoDAG(unittest.TestCase):
    def setUp(self):
        self.dag = OntoDAG()
        self.dag.put('A', [])
        self.dag.put('B', [])
        self.dag.put('C', [])
        self.dag.put('D', [])
        self.dag.put('F', [])
        self.dag.put('G', [])
        self.dag.put('AF', ['A', 'F'])
        self.dag.put('AB', ['A', 'B'])
        self.dag.put('BC', ['B', 'C'])
        self.dag.put('ABC', ['AB', 'BC'])
        self.dag.put('ABF', ['AB', 'AF'])
        self.dag.put('CD', ['C', 'D'])

    def test_common_subcategories(self):
        query_items = ['B', 'C']
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['ABC', 'BC'], sorted([item.name for item in common_subcategories], ))

    def test_ancestors_of_AF(self):
        ancestors = self.dag.get_ancestors(self.dag.nodes['AF'], self.dag.root.name)
        self.assertIsNotNone(ancestors)
        self.assertEqual(['A', 'F'], sorted([item.name for item in ancestors]))

    def test_descendant_count(self):
        descendants = self.dag.get_descendants(self.dag.nodes['A'])
        self.assertEqual(4, len(descendants))

    def test_descendant_count_after_put(self):
        self.dag.put('E', ['AB', 'CD'], optimized=True)
        descendants = self.dag.get_descendants(self.dag.nodes['A'])
        self.assertEqual(5, len(descendants))

    def test_descendant_count_after_remove(self):
        self.dag.remove('ABC')
        descendants = self.dag.get_descendants(self.dag.nodes['A'])
        self.assertEqual(3, len(descendants))

    def test_visualize(self):
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertTrue(os.path.isfile("ontodag_vis"))
        self.assertTrue(os.path.isfile("ontodag_vis.png"))
        os.remove("ontodag_vis")
        os.remove("ontodag_vis.png")

    def test_put_optimized(self):
        element_set_query = ['AB', 'CD']
        self.dag.put('E', element_set_query, optimized=True)
        query_items = ['ABC', 'CD']
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['E'], [item.name for item in common_subcategories])


if __name__ == '__main__':
    unittest.main()
