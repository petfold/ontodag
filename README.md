# OntoDAG

Associative memory and categories based on a directred acyclic graph data structure

## Specification

A Directed Acyclic Graph (DAG) associative storage and categorizer in Python. This data
structure a ontodag. You can store items into a ontodag and recall items from it. Each item will have a name (a string).
To store or "put" an item into a ontodag, you give it a name and a set of other names of already existing items that are
its supercategories. Give an error if the given supercategory name does not exist. Insert the new item into the DAG by
adding edges from all the supercategories specified. To recall or "get", you specify a set of item names, and you should
get all items that are subcategories of all these items. Can we do this step by step. Let's start by implementing the
DAG data structure.

## Roadmap

- [ ] Implement the basic DAG data structure (put, remove)
- [ ] Simplify definitions not to include unnecessary links (e.g. bird under animal, animal is not needed)
  - During put keep a dictionary of 'done' nodes of the inserted item and all its super categories
  - Insert a link only to nodes which are not 'done'
  - Increment counter only for items which are not 'done'
- [ ] Visualize graph (with python library - Graphviz)
- [ ] More extensive test cases
- [ ] Select suitable ontology for importing (to serve as the basis of the DAG)
- [ ] Sub-class of OntoDAG with counters (for statistics)
- [ ] Sub-class of OntoDAG with weights, i.e. conditional probabilities (for machine learning)
- [ ] Add and remove intermediate nodes to optimize search in the graph
- [ ] Implement space and time calculation for graph items (e.g. century, GPS bounding box)
- [ ] Port implementation to Golang
- [ ] Implement a REST API for the Golang (or Rust) implementation
- [ ] Interface with a graph database implementation.
- [ ] Implement a web interface for the REST API & host it on a website with user profiles
- [ ] Implement a limited functionality (DAG-only) graph database for Ethereum Swarm
- [ ] Design a plugin for Ethereum Swarm to store the DAG in a decentralized way