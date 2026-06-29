"""Language-agnostic in-memory knowledge graph."""

import json
import os
from typing import Dict, List, Optional, Set

from .edge import Edge
from .node import Node


class DuplicateNodeError(ValueError):
    """Raised when a node with an already-registered id is added."""


class DuplicateEdgeError(ValueError):
    """Raised when an edge with an already-registered id is added."""


class Graph:
    """An in-memory directed graph of `Node` and `Edge` records.

    Adjacency lists are maintained alongside the primary id-keyed
    stores so that the `get_edges_from`, `get_edges_to`, and
    `get_neighbors` lookups stay proportional to the queried node's
    degree rather than the size of the graph.

    The graph is intentionally permissive about edge endpoints: an
    `Edge` whose `is_resolved` flag is `False` may reference a
    `target_id` that does not (yet) exist as a `Node`. This is what
    lets parsers emit unresolved references during ingestion and have
    them linked up by a later resolution pass.
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, Node] = {}
        self._edges: Dict[str, Edge] = {}
        self._outgoing: Dict[str, Set[str]] = {}
        self._incoming: Dict[str, Set[str]] = {}

    # ----- mutation ---------------------------------------------------

    def add_node(self, node: Node) -> None:
        if not isinstance(node, Node):
            raise TypeError("Graph.add_node expects a Node instance")
        if node.id in self._nodes:
            raise DuplicateNodeError(f"Node with id {node.id!r} already exists")
        self._nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        if not isinstance(edge, Edge):
            raise TypeError("Graph.add_edge expects an Edge instance")
        if edge.id in self._edges:
            raise DuplicateEdgeError(f"Edge with id {edge.id!r} already exists")
        self._edges[edge.id] = edge
        self._outgoing.setdefault(edge.source_id, set()).add(edge.id)
        self._incoming.setdefault(edge.target_id, set()).add(edge.id)

    def remove_nodes_for_file(self, file_path: str) -> int:
        """Remove every node whose file_path matches, plus all edges that
        touch those nodes (as source or target). Returns the node count removed."""
        normalized = os.path.normpath(file_path)
        target_ids = [
            nid for nid, n in self._nodes.items()
            if os.path.normpath(n.file_path or "") == normalized
        ]
        for node_id in target_ids:
            edge_ids: Set[str] = set()
            edge_ids.update(self._outgoing.get(node_id, set()))
            edge_ids.update(self._incoming.get(node_id, set()))
            for eid in list(edge_ids):
                edge = self._edges.pop(eid, None)
                if edge is not None:
                    out = self._outgoing.get(edge.source_id)
                    if out is not None:
                        out.discard(eid)
                    inc = self._incoming.get(edge.target_id)
                    if inc is not None:
                        inc.discard(eid)
            self._nodes.pop(node_id, None)
            self._outgoing.pop(node_id, None)
            self._incoming.pop(node_id, None)
        return len(target_ids)

    # ----- read -------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    def get_edges_from(self, node_id: str) -> List[Edge]:
        return [self._edges[eid] for eid in self._outgoing.get(node_id, ())]

    def get_edges_to(self, node_id: str) -> List[Edge]:
        return [self._edges[eid] for eid in self._incoming.get(node_id, ())]

    def get_neighbors(self, node_id: str) -> List[Node]:
        """Return all nodes directly connected to `node_id` in either direction."""
        neighbor_ids: List[str] = []
        seen: Set[str] = set()
        for eid in self._outgoing.get(node_id, ()):
            other = self._edges[eid].target_id
            if other not in seen and other in self._nodes:
                seen.add(other)
                neighbor_ids.append(other)
        for eid in self._incoming.get(node_id, ()):
            other = self._edges[eid].source_id
            if other not in seen and other in self._nodes:
                seen.add(other)
                neighbor_ids.append(other)
        return [self._nodes[nid] for nid in neighbor_ids]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def has_edge(self, source_id: str, target_id: str) -> bool:
        for eid in self._outgoing.get(source_id, ()):
            if self._edges[eid].target_id == target_id:
                return True
        return False

    def all_nodes(self) -> List[Node]:
        return list(self._nodes.values())

    def all_edges(self) -> List[Edge]:
        return list(self._edges.values())

    @property
    def node_count(self) -> int:
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        return len(self._edges)

    # ----- persistence ------------------------------------------------

    def serialize_to_json(self, filepath: str) -> None:
        payload = {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": [e.to_dict() for e in self._edges.values()],
        }
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    @classmethod
    def deserialize_from_json(cls, filepath: str) -> "Graph":
        with open(filepath, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        graph = cls()
        for node_dict in payload.get("nodes", []):
            graph.add_node(Node.from_dict(node_dict))
        for edge_dict in payload.get("edges", []):
            graph.add_edge(Edge.from_dict(edge_dict))
        return graph
