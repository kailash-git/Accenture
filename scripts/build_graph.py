"""
build_graph.py
Builds the evidence graph from data/business_bi.db and persists it to
data/evidence_graph.gpickle, so it can be queried (see src/analytics/
graph_query.py) without rebuilding from scratch every time.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from src.analytics.graph_builder import build_graph
from src.analytics.graph_store import save_graph

DB_PATH = os.path.join(BASE_DIR, 'data', 'business_bi.db')
GRAPH_PATH = os.path.join(BASE_DIR, 'data', 'evidence_graph.gpickle')


def main():
    print(f"Building evidence graph from {DB_PATH} ...")
    graph = build_graph(DB_PATH)
    save_graph(graph, GRAPH_PATH)

    kinds = {}
    for _, a in graph.nodes(data=True):
        kinds[a['kind']] = kinds.get(a['kind'], 0) + 1

    print(f"Saved to {GRAPH_PATH}")
    print(f"  {graph.number_of_nodes()} nodes / {graph.number_of_edges()} edges")
    print(f"  PVM mismatches: {graph.graph.get('pvm_mismatches')}")
    for k, v in sorted(kinds.items()):
        print(f"  {k}: {v}")


if __name__ == '__main__':
    main()
