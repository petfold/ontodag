import os
import unittest
from dag import OntoDAG, OntoDAGVisualizer, Item


class TestOntoDAG(unittest.TestCase):
    def setUp(self):
        self.dag = OntoDAG()
        self.dag.put(Item('A'), [])
        self.dag.put(Item('B'), [])
        self.dag.put(Item('C'), [])
        self.dag.put(Item('D'), [])
        self.dag.put(Item('F'), [])
        self.dag.put(Item('G'), [])
        self.dag.put(Item('AF'), [Item('A'), Item('F')])
        self.dag.put(Item('AB'), [Item('A'), Item('B')])
        self.dag.put(Item('BC'), [Item('B'), Item('C')])
        self.dag.put(Item('ABC'), [Item('AB'), Item('BC')])
        self.dag.put(Item('ABF'), [Item('AB'), Item('AF')])
        self.dag.put(Item('CD'), [Item('C'), Item('D')])

    def test_common_subcategories(self):
        query_items = [Item('B'), Item('C')]
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['ABC', 'BC'], sorted([item.name for item in common_subcategories]))

    def test_ancestors_of_AF(self):
        ancestors = self.dag.get_ancestors(Item('AF'), {self.dag.root})
        self.assertIsNotNone(ancestors)
        self.assertEqual(['A', 'F'], sorted([item.name for item in ancestors]))

    def test_descendant_count(self):
        descendants = self.dag.get_descendants(Item('A'))
        self.assertEqual(4, len(descendants))

    def test_descendant_count_after_put(self):
        self.dag.put(Item('E'), [Item('AB'), Item('CD')], optimized=True)
        descendants = self.dag.get_descendants(Item('A'))
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertEqual(5, len(descendants))

    def test_descendant_count_after_remove(self):
        ancestor_node = Item('F')
        descendants_before = self.dag.get_descendants(ancestor_node)
        self.assertEqual(2, len(descendants_before))
        self.assertEqual(['ABF', 'AF'], sorted([subcategory.name for subcategory in descendants_before]))

        self.dag.remove(Item('AF'))

        descendants_after = self.dag.get_descendants(ancestor_node)
        self.assertEqual(1, len(descendants_after))
        self.assertEqual(['ABF'], [subcategory.name for subcategory in ancestor_node.neighbors])
        self.assertEqual(['AB', 'ABF'], sorted([subcategory.name for subcategory in Item('A').neighbors]))

    def test_visualize(self):
        visualizer = OntoDAGVisualizer()
        visualizer.visualize(self.dag)
        self.assertTrue(os.path.isfile('ontodag_vis'))
        self.assertTrue(os.path.isfile('ontodag_vis.png'))
        os.remove('ontodag_vis')
        os.remove('ontodag_vis.png')

    def test_put_optimized(self):
        element_set_query = [Item('AB'), Item('CD')]
        self.dag.put(Item('E'), element_set_query, optimized=True)
        query_items = [Item('ABC'), Item('CD')]
        common_subcategories = self.dag.get(query_items)
        self.assertEqual(['E'], [item.name for item in common_subcategories])


if __name__ == '__main__':
    unittest.main()
