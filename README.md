# OntoDAG

Associative memory and categories based on a directed acyclic graph data structure

## Specification

A Directed Acyclic Graph (DAG) associative storage and category manager in Python. You can store items into a ontodag and recall items from it. To store or "put" an item into a ontodag, you give it a name and a set of other names of already existing items that are its supercategories. To recall or "get", you specify a set of item names to get all items that are subcategories of all these items.

## Roadmap

- [x] Implement the basic DAG data structure (put, remove)
- [x] Simplify definitions not to include unnecessary links (e.g. bird under animal, animal is not needed)
  - During put keep a dictionary of 'done' nodes of the inserted item and all its super categories
  - Insert a link only to nodes which are not 'done'
  - Increment counter only for items which are not 'done'
- [x] Save/load data structure into/from file (try PKL)
- [x] Load ontology from file (e.g. OWL)
- [x] Visualize graph (with python library - Graphviz)
- [x] More extensive test cases
- [x] Select suitable ontology for importing (to serve as the basis of the DAG)
- [x] Sub-class of OntoDAG with counters (for statistics)
- [ ] Predicated (parametric) items. Dealing with items not stored in the graph (e.g. numbers, intervals, geo coordinates, areas; general, hierarchical types (types stored in the graph))
- [ ] Implement space and time calculation for graph items (e.g. century, GPS bounding box)
  - categories for item types, e.g. point in time, time interval, geo coordinates, geo area, url
  - way to handle non-stored numerical types (time intervals, geo coordinates, areas, numbers, arbitrary types)
  - way to store and retrieve ordered values (photo with exact time in response to "last week")
  - ways to define (partial) ordering function
  - file types (hierarchical, e.g. image, png)
- [ ] Name usage across different instances of OntoDAG:
  - namespaces
  - avoiding confusing names (different language and usage, spelling)
  - ability to merge DAGs with different name usage, using namespaces
- [ ] Optimize retrieval and storage by choosing subsets of query items and finding existing nodes already stored in the DAG.
- [ ] Add and remove intermediate nodes to optimize search in the graph
- [ ] Port implementation to Golang
- [ ] Implement a REST API for the Golang (or Rust) implementation
- [ ] Interface with a graph database implementation.
- [ ] Implement a web interface for the REST API & host it on a website with user profiles
- [ ] Implement a limited functionality (DAG-only) graph database for Ethereum Swarm
- [ ] Design a plugin for Ethereum Swarm to store the DAG in a decentralized way

## Potential Applications
* Using the ontology graph for content categorization instead of folders
* Replace content tags with a more structured ontology
* Access control (ACT) groups
* Memberships in organizations and gate content based on membership
* Communication channel groups defined by the ontology
* Fostering deals within a universal marketplace for services and goods
