"""Graph traversal engine for the Incident Diagnostics Engine.

Given a ParsedIncident, locates entry nodes in the knowledge graph and
walks backward through CALLS / IMPORTS / EXTENDS edges to surface the
most likely root-cause candidates.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .scoring_utils import days_since_iso, matched_keywords
from .scoring_config import DEFAULT_WEIGHTS, ScoringWeights

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CandidateNode:
    node_id: str = ""
    node_name: str = ""
    file_path: str = ""
    line_number: int = 0
    node_type: str = ""
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    git_evidence: str = ""
    hops_from_entry: int = 0


@dataclass
class TraversalResult:
    entry_nodes: List[str] = field(default_factory=list)
    visited_nodes: List[str] = field(default_factory=list)
    candidate_root_causes: List[CandidateNode] = field(default_factory=list)
    hops_completed: int = 0
    traversal_path: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TraversalEngine:

    def __init__(self, weights: Optional[ScoringWeights] = None):
        self._weights = weights or DEFAULT_WEIGHTS

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def find_entry_nodes(
        self,
        incident: Any,
        graph: Any,
        enricher: Any,
    ) -> List[str]:
        """Find starting nodes for traversal.

        If incident has stack frames — use exact name and file matching only.
        TF-IDF is never used for stack trace inputs because exact matching
        is always more precise.

        If incident has no frames — use TF-IDF semantic search as fallback
        for natural language queries.
        """
        try:
            if incident.frames:
                return self._exact_match_entry_nodes(incident, graph)
            else:
                return self._semantic_entry_nodes(incident, graph, enricher)
        except Exception:
            return []

    def traverse(
        self,
        entry_nodes: List[str],
        graph: Any,
        incident: Any,
        max_hops: int = 4,
    ) -> TraversalResult:
        """BFS backward traversal from entry nodes. Never crashes.

        For natural language queries (no frames) max_hops is forced to 0 —
        TF-IDF entry nodes are already the candidates; hopping away from them
        adds noise rather than tracing a causal chain.
        """
        if not getattr(incident, "frames", None):
            max_hops = 0
        try:
            return self._traverse_internal(entry_nodes, graph, incident, max_hops)
        except Exception as ex:
            result = TraversalResult()
            result.entry_nodes = list(entry_nodes or [])
            result.errors.append("traverse crashed: " + repr(ex))
            return result

    # -----------------------------------------------------------------------
    # Entry-node discovery
    # -----------------------------------------------------------------------

    def _exact_match_entry_nodes(
        self, incident: Any, graph: Any,
    ) -> List[str]:
        """Exact name and file path matching from stack trace frames.

        For each frame, collects all graph nodes with matching name and file,
        then uses line-number proximity to resolve same-file collisions: the
        correct node is the one defined closest to (but not after) the frame
        line — i.e. the innermost enclosing function definition.
        """
        results: Dict[str, float] = {}

        frames = getattr(incident, "frames", None) or []
        n_frames = len(frames)

        for i, frame in enumerate(frames):
            if not frame.function_name:
                continue

            frame_file = (frame.file_path or "").replace("\\", "/")
            if not frame_file:
                continue

            # Last frame (deepest, closest to exception) → weight 1.0
            # First frame (outermost caller) → weight 0.4
            position_weight = (
                0.4 + 0.6 * (i / (n_frames - 1)) if n_frames > 1 else 1.0
            )

            # Collect all file-matching candidates for this frame.
            #refactoring
            candidates: List[Any] = []
            for node in graph.all_nodes():
                if node.type not in ("function", "class"):
                    continue
                if node.name != frame.function_name:
                    continue

                node_file = (node.file_path or "").replace("\\", "/")
                file_match = (
                    node_file.endswith(frame_file)
                    or frame_file.endswith(node_file.split("/")[-1])
                    or node_file.split("/")[-1] == frame_file.split("/")[-1]
                )
                if file_match:
                    candidates.append(node)

            if not candidates:
                continue

            # Line-number proximity: prefer the node defined closest to but
            # not after the frame line (innermost enclosing definition).
            # Fall back to all candidates when frame line is unknown (0).
            frame_line = frame.line_number or 0
            if frame_line > 0:
                before = [n for n in candidates
                          if (n.line_number or 0) <= frame_line]
                if before:
                    # Keep only the closest definition.
                    candidates = [max(before, key=lambda n: n.line_number or 0)]

            for node in candidates:
                if node.id not in results or position_weight > results[node.id]:
                    results[node.id] = position_weight

        ranked = sorted(results.items(), key=lambda kv: kv[1], reverse=True)
        return [nid for nid, _ in ranked[:5]]

    def _semantic_entry_nodes(
        self, incident: Any, graph: Any, enricher: Any,
    ) -> List[str]:
        """TF-IDF semantic search for natural language queries."""
        if not incident.keywords or enricher is None:
            return []
        query = " ".join(incident.keywords)
        try:
            raw = enricher.search(query, graph, top_k=10)
        except Exception:
            return []
        results = []
        for node_id, score in (raw or []):
            node = graph.get_node(node_id)
            if node is not None and node.type in ("function", "class"):
                results.append((node_id, score))
        return [nid for nid, _ in results[:5]]

    # -----------------------------------------------------------------------
    # Traversal
    # -----------------------------------------------------------------------

    def _traverse_internal(
        self,
        entry_nodes: List[str],
        graph: Any,
        incident: Any,
        max_hops: int,
    ) -> TraversalResult:
        result = TraversalResult()
        result.entry_nodes = list(entry_nodes or [])

        if not entry_nodes:
            missing = ", ".join(
                f.function_name
                for f in (getattr(incident, "frames", None) or [])
                if f.function_name
            )
            result.errors.append(
                "No entry nodes found — crash site not in graph. "
                "Functions searched: " + (missing or "none extracted from trace")
            )
            return result

        visited: set = set()
        all_candidates: List[CandidateNode] = []

        # Deduplicate entry nodes while preserving order.
        current_level: List[str] = list(dict.fromkeys(
            nid for nid in entry_nodes if nid
        ))

        for hop in range(max_hops + 1):
            if not current_level:
                break

            result.hops_completed = hop
            # Accumulate next-hop node ids (dict preserves insertion order,
            # acts as an ordered set).
            next_level_map: Dict[str, None] = {}

            for node_id in current_level:
                if node_id in visited:
                    continue
                visited.add(node_id)

                node = graph.get_node(node_id)
                if node is None:
                    result.errors.append("node not found: " + node_id)
                    continue

                result.traversal_path.append(node_id)

                score, reasons, git_evidence = self._evaluate_node(
                    node, graph, incident, hop
                )
                all_candidates.append(CandidateNode(
                    node_id=node.id,
                    node_name=node.name or "",
                    file_path=node.file_path or "",
                    line_number=node.line_number if isinstance(node.line_number, int) else 0,
                    node_type=node.type or "",
                    score=score,
                    reasons=reasons,
                    git_evidence=git_evidence,
                    hops_from_entry=hop,
                ))

                if hop >= max_hops:
                    continue

                # Backward: nodes that call / import / extend current node.
                try:
                    for edge in graph.get_edges_to(node_id):
                        if edge.relationship in ("CALLS", "IMPORTS", "EXTENDS"):
                            if edge.source_id not in visited:
                                next_level_map[edge.source_id] = None
                except Exception as ex:
                    result.errors.append(
                        "get_edges_to failed for " + node_id + ": " + repr(ex)
                    )

                # Forward CALLS / IMPORTS: callees and module dependencies the
                # node itself reaches. A crash often surfaces where bad data is
                # *used*, while the fault lives in a function it *called* (or a
                # config value that callee read) — a node that is not in the
                # stack trace at all. Following forward CALLS lets traversal walk
                # downstream into that callee chain; forward IMPORTS still picks
                # up broken module-level dependencies.
                try:
                    for edge in graph.get_edges_from(node_id):
                        if edge.relationship in ("CALLS", "IMPORTS"):
                            if edge.target_id not in visited:
                                next_level_map[edge.target_id] = None
                except Exception as ex:
                    result.errors.append(
                        "get_edges_from failed for " + node_id + ": " + repr(ex)
                    )

            # Beam width: score next-level candidates and keep only the top 15.
            if next_level_map:
                scored_next: List[Tuple[float, str]] = []
                for nid in next_level_map:
                    if nid in visited:
                        continue
                    node = graph.get_node(nid)
                    if node is None:
                        continue
                    s = self._score_node(node, graph, incident, hop + 1)
                    scored_next.append((s, nid))
                # Score desc, then node id asc. Every candidate here is at
                # the same hop, so id is what keeps the top-15 cut from
                # depending on set/dict iteration order across runs.
                scored_next.sort(key=lambda t: (-t[0], t[1]))
                current_level = [nid for _, nid in scored_next[:15]]
            else:
                current_level = []

        result.visited_nodes = list(visited)
        # Rank by score desc; break ties by proximity to the crash site
        # (fewer hops wins), then by node id so the order is fully
        # deterministic and never depends on hash/iteration order.
        result.candidate_root_causes = sorted(
            all_candidates,
            key=lambda c: (-c.score, c.hops_from_entry, c.node_id),
        )
        return result

    # -----------------------------------------------------------------------
    # Scoring
    # -----------------------------------------------------------------------

    def _score_node(
        self, node: Any, graph: Any, incident: Any, hops_from_entry: int
    ) -> float:
        """Public interface: returns score float only."""
        score, _, _ = self._evaluate_node(node, graph, incident, hops_from_entry)
        return score

    def _evaluate_node(
        self, node: Any, graph: Any, incident: Any, hops_from_entry: int
    ) -> Tuple[float, List[str], str]:
        """Compute (score, reasons, git_evidence) for a candidate node."""
        reasons: List[str] = []
        meta: Dict = node.metadata if isinstance(node.metadata, dict) else {}

        # Signal 1 — proximity to crash site
        base_score = 1.0 / (1.0 + hops_from_entry)
        if hops_from_entry == 0:
            reasons.append("Entry point from stack trace")

        # Signal 2 — git recency
        git_score = 0.0
        last_commit_date = meta.get("last_commit_date", "") or ""
        days_since = days_since_iso(last_commit_date)
        if days_since is not None:
            if days_since <= 1:
                git_score = 1.0
            elif days_since <= 7:
                git_score = 0.8
            elif days_since <= 30:
                git_score = 0.5
            else:
                git_score = 0.2

        if git_score > 0.5 and days_since is not None:
            commit_msg = (meta.get("last_commit_message") or "").split("\n")[0][:80]
            reasons.append(
                "Modified " + str(days_since) + " days ago: " + commit_msg
            )

        # Signal 3 — keyword match
        keyword_score = 0.0
        keywords = getattr(incident, "keywords", None) or []
        matched_kws = matched_keywords(
            keywords,
            node.name or "",
            getattr(node, "docstring", None) or "",
            meta.get("last_commit_message", "") or "",
        )
        if keywords:
            keyword_score = len(matched_kws) / len(keywords)

        if keyword_score > 0:
            reasons.append("Keyword match: " + ", ".join(matched_kws[:5]))

        # Signal 4 — error type alignment via RAISES edges only.
        # A node that explicitly raises the incident's error type gets full
        # credit. Zero if no matching RAISES edge exists — no text fallback.
        # Cache outgoing edges here — Signal 5 reuses them to avoid a second call.
        error_type_score = 0.0
        error_type = getattr(incident, "error_type", "") or ""
        outgoing_edges: List[Any] = []
        try:
            outgoing_edges = list(graph.get_edges_from(node.id))
        except Exception:
            pass

        if error_type:
            for edge in outgoing_edges:
                if edge.relationship != "RAISES":
                    continue
                raised = graph.get_node(edge.target_id)
                raised_name = (raised.name if raised else None) or edge.target_id or ""
                raised_short = raised_name.split(".")[-1]
                if raised_short == error_type or raised_name == error_type:
                    error_type_score = 1.0
                    reasons.append("Raises " + error_type + " directly")
                    break

        # Signal 5 — connectivity (entry nodes only, CALLS edges only).
        # For hop > 0 nodes this is noise: a utility function discovered via
        # traversal can have dozens of outgoing edges without being a root cause.
        edge_score = 0.0
        outgoing_count = 0
        if hops_from_entry == 0:
            outgoing_count = sum(
                1 for e in outgoing_edges if e.relationship == "CALLS"
            )
            edge_score = min(1.0, outgoing_count / 10.0)
            if edge_score > 0.5:
                reasons.append(
                    "High connectivity: " + str(outgoing_count) + " outgoing calls"
                )

        w = self._weights
        final_score = round(
            base_score       * w.proximity
            + git_score      * w.git
            + keyword_score  * w.keyword
            + error_type_score * w.error_type
            + edge_score     * w.connectivity,
            4,
        )

        # Git evidence string
        git_evidence = ""
        commit_msg = (meta.get("last_commit_message") or "").strip()
        if commit_msg:
            git_evidence = commit_msg.split("\n")[0][:120]
            if last_commit_date:
                git_evidence += " (" + last_commit_date[:10] + ")"

        return final_score, reasons, git_evidence

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _extract_file_stem(self, file_path: str) -> str:
        """'order.py' → 'order', '/path/to/order.py' → 'order'."""
        if not file_path:
            return ""
        return os.path.splitext(os.path.basename(file_path))[0]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import pickle
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _SRC = os.path.dirname(_HERE)
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)

    from diagnosis.stack_trace_parser import StackTraceParser
    from semantic.tfidf_enricher import TFIDFEnricher

    if len(sys.argv) < 3:
        print("Usage: python traversal_engine.py <pickle_path> <tfidf_path>")
        sys.exit(1)

    with open(sys.argv[1], "rb") as f:
        graph = pickle.load(f)

    enricher = TFIDFEnricher.load(sys.argv[2])

    stack_trace = """
Traceback (most recent call last):
  File "app.py", line 8, in handle_request
    return service.place_order(request.cart)
  File "order.py", line 7, in place_order
    payment.charge(cart.total)
  File "payment.py", line 9, in charge
    return cart.total
AttributeError: NoneType object has no attribute total
"""

    parser = StackTraceParser()
    incident = parser.parse(stack_trace)

    engine = TraversalEngine()
    entry_nodes = engine.find_entry_nodes(incident, graph, enricher)
    print(f"Entry nodes found: {len(entry_nodes)}")
    for nid in entry_nodes:
        node = graph.get_node(nid)
        print(f"  {node.name} ({node.type}) — {node.file_path}")

    result = engine.traverse(entry_nodes, graph, incident)
    print(f"\nTraversal complete — {result.hops_completed} hops")
    print(f"Nodes visited: {len(result.visited_nodes)}")
    print(f"\nTop 5 candidates:")
    for candidate in result.candidate_root_causes[:5]:
        print(f"  {candidate.score:.3f}  {candidate.node_name} ({candidate.node_type})")
        for reason in candidate.reasons:
            print(f"    - {reason}")
