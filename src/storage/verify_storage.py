"""Storage verifier.

Loads the JSON and pickle dumps produced by the ingestion pipeline and
runs seven integrity checks:

  1. both files exist on disk
  2. JSON deserializes via `Graph.deserialize_from_json`
  3. pickle deserializes via `pickle.load`
  4. node + edge counts match between the two representations, with
     spot-checks on 10 random nodes and 10 random edges
  5. resolved-edge targets point to real nodes (dangling = bug);
     source ids that look like node ids also resolve
  6. every node has a non-empty id, a type from VALID_NODE_TYPES, and
     a non-empty file_path
  7. `Graph.get_neighbors` works on a real function node

CLI:

    python verify_storage.py <json_path> <pickle_path>
"""

import os
import pickle
import random
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Make `src/` importable so absolute imports work whether this file is
# invoked as a script or imported as part of the `storage` package.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from graph.graph import Graph  # noqa: E402
from graph.node import VALID_NODE_TYPES  # noqa: E402


# Cap how many per-check problems we add to `errors` so a totally
# broken graph doesn't flood the report.
_MAX_ERRORS_PER_CHECK = 5


@dataclass
class VerificationReport:
    json_path: str = ""
    pickle_path: str = ""
    json_file_size_kb: float = 0.0
    pickle_file_size_kb: float = 0.0
    json_node_count: int = 0
    json_edge_count: int = 0
    pickle_node_count: int = 0
    pickle_edge_count: int = 0
    counts_match: bool = False
    dangling_edges: int = 0
    resolved_edges: int = 0
    unresolved_edges: int = 0
    nodes_by_type: Dict[str, int] = field(default_factory=dict)
    traversal_test_passed: bool = False
    all_checks_passed: bool = False
    errors: List[str] = field(default_factory=list)


class StorageVerifier:
    """Run the seven storage-integrity checks and return a report."""

    # ---- main entry point -------------------------------------------

    def verify(self, json_path: str, pickle_path: str) -> VerificationReport:
        report = VerificationReport()
        report.json_path = json_path
        report.pickle_path = pickle_path

        # Check 1 — files exist
        if not self._check_files_exist(json_path, pickle_path, report):
            return report

        # Checks 2 & 3 — load each representation
        json_graph = self._load_json(json_path, report)
        pickle_graph = self._load_pickle(pickle_path, report)
        if json_graph is None or pickle_graph is None:
            return report

        # Check 4 — consistency between the two
        self._check_consistency(json_graph, pickle_graph, report)

        # Checks 5–7 — run on the JSON graph (already verified to match
        # the pickle one in step 4, so the result is the same either way)
        self._check_structure(json_graph, report)
        self._check_nodes(json_graph, report)
        self._check_traversal(json_graph, report)

        report.all_checks_passed = (
            len(report.errors) == 0
            and report.counts_match
            and report.dangling_edges == 0
            and report.traversal_test_passed
        )
        return report

    # ---- Check 1 ----------------------------------------------------

    def _check_files_exist(
        self, json_path: str, pickle_path: str, report: VerificationReport,
    ) -> bool:
        ok = True
        if not os.path.isfile(json_path):
            report.errors.append("JSON file not found: " + json_path)
            ok = False
        else:
            try:
                report.json_file_size_kb = os.path.getsize(json_path) / 1024.0
            except OSError as ex:
                report.errors.append("stat JSON failed: " + repr(ex))
                ok = False
        if not os.path.isfile(pickle_path):
            report.errors.append("Pickle file not found: " + pickle_path)
            ok = False
        else:
            try:
                report.pickle_file_size_kb = os.path.getsize(pickle_path) / 1024.0
            except OSError as ex:
                report.errors.append("stat pickle failed: " + repr(ex))
                ok = False
        return ok

    # ---- Check 2 ----------------------------------------------------

    def _load_json(
        self, json_path: str, report: VerificationReport,
    ) -> Optional[Graph]:
        try:
            g = Graph.deserialize_from_json(json_path)
        except Exception as ex:
            report.errors.append("JSON load failed: " + repr(ex))
            return None
        report.json_node_count = g.node_count
        report.json_edge_count = g.edge_count
        return g

    # ---- Check 3 ----------------------------------------------------

    def _load_pickle(
        self, pickle_path: str, report: VerificationReport,
    ) -> Optional[Graph]:
        try:
            with open(pickle_path, "rb") as fh:
                g = pickle.load(fh)
        except Exception as ex:
            report.errors.append("pickle load failed: " + repr(ex))
            return None
        if not isinstance(g, Graph):
            report.errors.append(
                "pickle did not contain a Graph (got " + type(g).__name__ + ")"
            )
            return None
        report.pickle_node_count = g.node_count
        report.pickle_edge_count = g.edge_count
        return g

    # ---- Check 4 ----------------------------------------------------

    def _check_consistency(
        self,
        json_graph: Graph,
        pickle_graph: Graph,
        report: VerificationReport,
    ) -> None:
        counts_ok = True
        if json_graph.node_count != pickle_graph.node_count:
            report.errors.append(
                "node count mismatch: JSON=" + str(json_graph.node_count)
                + " pickle=" + str(pickle_graph.node_count)
            )
            counts_ok = False
        if json_graph.edge_count != pickle_graph.edge_count:
            report.errors.append(
                "edge count mismatch: JSON=" + str(json_graph.edge_count)
                + " pickle=" + str(pickle_graph.edge_count)
            )
            counts_ok = False

        # Spot-check 10 random nodes
        nodes = json_graph.all_nodes()
        if nodes:
            sample = random.sample(nodes, min(10, len(nodes)))
            mismatches = 0
            for jn in sample:
                pn = pickle_graph.get_node(jn.id)
                if pn is None:
                    if mismatches < _MAX_ERRORS_PER_CHECK:
                        report.errors.append("node missing in pickle: " + jn.id)
                    mismatches += 1
                    continue
                if pn.to_dict() != jn.to_dict():
                    if mismatches < _MAX_ERRORS_PER_CHECK:
                        report.errors.append(
                            "node fields differ for " + jn.id
                        )
                    mismatches += 1
            if mismatches:
                counts_ok = False

        # Spot-check 10 random edges. Pickle edges keyed by id for O(1)
        # lookup so we don't pay O(N) per sampled edge.
        edges = json_graph.all_edges()
        if edges:
            pickle_edges_by_id = {e.id: e for e in pickle_graph.all_edges()}
            sample = random.sample(edges, min(10, len(edges)))
            mismatches = 0
            for je in sample:
                pe = pickle_edges_by_id.get(je.id)
                if pe is None:
                    if mismatches < _MAX_ERRORS_PER_CHECK:
                        report.errors.append("edge missing in pickle: " + je.id)
                    mismatches += 1
                    continue
                if pe.to_dict() != je.to_dict():
                    if mismatches < _MAX_ERRORS_PER_CHECK:
                        report.errors.append(
                            "edge fields differ for " + je.id
                        )
                    mismatches += 1
            if mismatches:
                counts_ok = False

        report.counts_match = counts_ok

    # ---- Check 5 ----------------------------------------------------

    def _check_structure(
        self, graph: Graph, report: VerificationReport,
    ) -> None:
        node_ids = {n.id for n in graph.all_nodes()}
        dangling = 0
        resolved = 0
        unresolved = 0
        missing_sources = 0

        for edge in graph.all_edges():
            # Source check: only flag when source LOOKS like a node id
            # (contains "::"). Unresolved DECORATES legitimately carries
            # a bare name string as its source until resolution rewrites
            # it; complaining about that would be noise.
            if "::" in edge.source_id and edge.source_id not in node_ids:
                if missing_sources < _MAX_ERRORS_PER_CHECK:
                    report.errors.append(
                        "edge " + edge.id + " source missing: " + edge.source_id
                    )
                missing_sources += 1

            if edge.is_resolved:
                resolved += 1
                if edge.target_id not in node_ids:
                    dangling += 1
                    if dangling <= _MAX_ERRORS_PER_CHECK:
                        report.errors.append(
                            "dangling edge " + edge.id
                            + " (resolved, missing target " + edge.target_id + ")"
                        )
            else:
                unresolved += 1

        report.dangling_edges = dangling
        report.resolved_edges = resolved
        report.unresolved_edges = unresolved

    # ---- Check 6 ----------------------------------------------------

    def _check_nodes(self, graph: Graph, report: VerificationReport) -> None:
        counts: Dict[str, int] = {}
        bad_id = 0
        bad_type = 0
        bad_path = 0
        for node in graph.all_nodes():
            if not node.id:
                if bad_id < _MAX_ERRORS_PER_CHECK:
                    report.errors.append("node with empty id (name=" + repr(node.name) + ")")
                bad_id += 1
            if node.type not in VALID_NODE_TYPES:
                if bad_type < _MAX_ERRORS_PER_CHECK:
                    report.errors.append(
                        "node " + node.id + " has invalid type: " + repr(node.type)
                    )
                bad_type += 1
            if not node.file_path:
                if bad_path < _MAX_ERRORS_PER_CHECK:
                    report.errors.append("node " + node.id + " has empty file_path")
                bad_path += 1
            counts[node.type] = counts.get(node.type, 0) + 1
        report.nodes_by_type = counts

    # ---- Check 7 ----------------------------------------------------

    def _check_traversal(self, graph: Graph, report: VerificationReport) -> None:
        function_nodes = [n for n in graph.all_nodes() if n.type == "function"]
        if not function_nodes:
            # An empty repo or one without functions is not an error;
            # there's just nothing meaningful to traverse from.
            print("Traversal test: no function nodes available, skipping")
            report.traversal_test_passed = True
            return
        target = function_nodes[0]
        try:
            neighbors = graph.get_neighbors(target.id)
        except Exception as ex:
            report.errors.append("get_neighbors crashed: " + repr(ex))
            return
        if not isinstance(neighbors, list):
            report.errors.append(
                "get_neighbors returned " + type(neighbors).__name__
                + ", expected list"
            )
            return
        report.traversal_test_passed = True
        print(
            "Traversal test: function " + repr(target.name)
            + " has " + str(len(neighbors)) + " neighbor(s)"
        )


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python verify_storage.py <json_path> <pickle_path>")
        sys.exit(1)
    verifier = StorageVerifier()
    report = verifier.verify(sys.argv[1], sys.argv[2])
    print("\n=== Storage Verification Report ===")
    print("JSON file size: {:.1f} KB".format(report.json_file_size_kb))
    print("Pickle file size: {:.1f} KB".format(report.pickle_file_size_kb))
    print("Nodes: " + str(report.json_node_count))
    print("Edges: " + str(report.json_edge_count))
    print("Counts match: " + str(report.counts_match))
    print("Resolved edges: " + str(report.resolved_edges))
    print("Unresolved edges: " + str(report.unresolved_edges))
    print("Dangling edges: " + str(report.dangling_edges))
    print("Nodes by type: " + str(report.nodes_by_type))
    print("Traversal test: " + ("PASSED" if report.traversal_test_passed else "FAILED"))
    print("All checks passed: " + str(report.all_checks_passed))
    if report.errors:
        print("\nErrors:")
        for err in report.errors:
            print("  - " + err)
