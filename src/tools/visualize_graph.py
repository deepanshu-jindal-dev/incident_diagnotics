#!/usr/bin/env python3
"""Interactive visualizer for the Code Knowledge Graph.

Loads a pickled `graph.graph.Graph`, converts it to a NetworkX graph, and
renders an interactive Pyvis HTML file. Nodes are colored by node type and
edges by relationship type. Supports relationship filtering, random node
sampling for large graphs, and a 2-hop neighborhood view around a named node.

Usage:

    PYTHONPATH=src python3 src/tools/visualize_graph.py \\
        --input output/merged_graph.pkl \\
        --output output/graph_visualization.html \\
        [--rel-types CALLS,IMPORTS] \\
        [--max-nodes 500] \\
        [--center-node get_source]
"""

import argparse
import os
import pickle
import random
import sys
from collections import Counter

import networkx as nx
from pyvis.network import Network

# Make `src/` importable so the pickled `graph.graph.Graph` (and Node/Edge)
# classes resolve during unpickling.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


# ── Styling ────────────────────────────────────────────────────────────
NODE_COLORS = {
    "function": "blue",
    "class": "green",
    "module": "orange",
    "method": "purple",
}
NODE_DEFAULT_COLOR = "grey"

EDGE_COLORS = {
    "CALLS": "red",
    "IMPORTS": "blue",
    "EXTENDS": "green",
    "RAISES": "orange",
    "CONTAINS": "grey",
}
EDGE_DEFAULT_COLOR = "lightgrey"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="visualize_graph.py",
        description="Render a Code Knowledge Graph as an interactive HTML page.",
    )
    parser.add_argument("--input", default="output/merged_graph.pkl",
                        help="path to the graph pickle file")
    parser.add_argument("--output",
                        default=os.path.join(_HERE, "output", "graph_visualization.html"),
                        help="path to the HTML output file "
                             "(default: src/tools/output/graph_visualization.html)")
    parser.add_argument("--rel-types", default="ALL",
                        help="comma-separated relationship types to include "
                             "(default ALL)")
    parser.add_argument("--max-nodes", type=int, default=500,
                        help="max nodes to render; sample randomly if exceeded "
                             "(default 500)")
    parser.add_argument("--center-node", default=None,
                        help="node name; if given, show only nodes within 2 hops")
    return parser.parse_args()


def _node_tooltip(node) -> str:
    doc = (node.docstring or "")[:100]
    return (
        f"<b>{node.name}</b><br>"
        f"id: {node.id}<br>"
        f"type: {node.type}<br>"
        f"file: {node.file_path}<br>"
        f"docstring: {doc}"
    )


def _edge_tooltip(edge) -> str:
    return (
        f"relationship: {edge.relationship}<br>"
        f"source: {edge.source_id}<br>"
        f"target: {edge.target_id}"
    )


def main() -> None:
    args = _parse_args()

    # ── Load graph ──────────────────────────────────────────────────────
    try:
        with open(args.input, "rb") as fh:
            graph = pickle.load(fh)
    except Exception as ex:
        print(f"Error: could not load graph from {args.input}: {ex}")
        sys.exit(1)

    nodes_by_id = {n.id: n for n in graph.all_nodes()}

    # ── Filter edges by relationship type ───────────────────────────────
    if args.rel_types.strip().upper() == "ALL":
        rel_filter = None
    else:
        rel_filter = {r.strip() for r in args.rel_types.split(",") if r.strip()}

    edges = []
    for e in graph.all_edges():
        if rel_filter is not None and e.relationship not in rel_filter:
            continue
        # Only keep edges whose endpoints are both real, rendered nodes.
        if e.source_id in nodes_by_id and e.target_id in nodes_by_id:
            edges.append(e)

    # ── Build a NetworkX graph (for hop-distance computation) ───────────
    nxg = nx.DiGraph()
    nxg.add_nodes_from(nodes_by_id.keys())
    for e in edges:
        nxg.add_edge(e.source_id, e.target_id)

    # ── Optional: restrict to a 2-hop neighborhood around --center-node ─
    if args.center_node:
        centers = [nid for nid, n in nodes_by_id.items()
                   if n.name == args.center_node]
        if not centers:
            print(f"Error: no node named {args.center_node!r} found in graph")
            sys.exit(1)
        undirected = nxg.to_undirected(as_view=True)
        keep = set()
        for c in centers:
            keep |= set(nx.ego_graph(undirected, c, radius=2).nodes())
        node_ids = keep
    else:
        node_ids = set(nodes_by_id.keys())

    # ── Random sampling if over the cap ─────────────────────────────────
    if len(node_ids) > args.max_nodes:
        node_ids = set(random.sample(sorted(node_ids), args.max_nodes))

    # Keep only edges fully inside the final node set.
    edges = [e for e in edges
             if e.source_id in node_ids and e.target_id in node_ids]

    # ── Build the Pyvis network ─────────────────────────────────────────
    net = Network(height="800px", width="100%", directed=True,
                  bgcolor="#ffffff", font_color="#222222",
                  cdn_resources="in_line")
    net.barnes_hut()

    for nid in node_ids:
        node = nodes_by_id[nid]
        net.add_node(
            nid,
            label=node.name,
            title=_node_tooltip(node),
            color=NODE_COLORS.get(node.type, NODE_DEFAULT_COLOR),
        )

    for e in edges:
        net.add_edge(
            e.source_id, e.target_id,
            title=_edge_tooltip(e),
            color=EDGE_COLORS.get(e.relationship, EDGE_DEFAULT_COLOR),
        )

    # ── Summary ─────────────────────────────────────────────────────────
    rel_counts = Counter(e.relationship for e in edges)
    print("=== Graph Visualization Summary ===")
    print(f"  Total nodes rendered: {len(node_ids)}")
    print(f"  Total edges rendered: {len(edges)}")
    print("  Edges by relationship type:")
    if rel_counts:
        for rel, count in sorted(rel_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"    {rel:<14} {count}")
    else:
        print("    (none)")

    # ── Save ────────────────────────────────────────────────────────────
    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    net.write_html(args.output, notebook=False, open_browser=False)
    print(f"\nSaved interactive visualization to {args.output}")


if __name__ == "__main__":
    main()
