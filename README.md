# OntoDAG

Associative memory and categories based on a directed acyclic graph data structure

## Specification

A Directed Acyclic Graph (DAG) associative storage and category manager in Python. You can store items into a ontodag and recall items from it. To store or "put" an item into a ontodag, you give it a name and a set of other names of already existing items that are its supercategories. To recall or "get", you specify a set of item names to get all items that are subcategories of all these items.

## Roadmap

- [ ] Implement the basic DAG data structure (put, remove)
- [ ] Simplify definitions not to include unnecessary links (e.g. bird under animal, animal is not needed)
  - During put keep a dictionary of 'done' nodes of the inserted item and all its super categories
  - Insert a link only to nodes which are not 'done'
  - Increment counter only for items which are not 'done'
- [ ] Save/load data structure into/from file (try PKL)
- [ ] Load ontology from file (e.g. OWL)
- [ ] Visualize graph (with python library - Graphviz)
- [ ] More extensive test cases
- [ ] Select suitable ontology for importing (to serve as the basis of the DAG)
- [ ] Sub-class of OntoDAG with counters (for statistics)
- [ ] Optimize retrieval and storage by choosing subsets of query items and finding existing nodes already stored in the DAG.
- [ ] Add and remove intermediate nodes to optimize search in the graph
- [ ] Implement space and time calculation for graph items (e.g. century, GPS bounding box)
  - categories for item types, e.g. point in time, time interval, geo coordinates, geo area, url
  - way to handle non-stored numerical types (time intervals, geo coordinates, areas, numbers, arbitrary types)
  - way to store and retrieve ordered values (photo with exact time in response to "last week")
  - ways to define (partial) ordering function
  - file types (hierarchical, e.g. image, png)
- [ ] Port implementation to Golang
- [ ] Implement a REST API for the Golang (or Rust) implementation
- [ ] Interface with a graph database implementation.
- [ ] Implement a web interface for the REST API & host it on a website with user profiles
- [ ] Implement a limited functionality (DAG-only) graph database for Ethereum Swarm
- [ ] Design a plugin for Ethereum Swarm to store the DAG in a decentralized way
