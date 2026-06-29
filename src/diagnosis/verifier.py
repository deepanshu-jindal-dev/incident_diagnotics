"""Candidate root-cause verifier for the Incident Diagnostics Engine.

Runs three independent checks on each CandidateNode produced by
TraversalEngine and combines them into a VerificationResult with a
confidence level and an explanation string ready for an LLM prompt.
"""

import os
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Any, List, Optional

from .scoring_utils import days_since_iso, matched_keywords

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    candidate: Any = None                    # CandidateNode
    is_valid: bool = False
    confidence: str = "low"                  # "high" | "medium" | "low"
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    path_exists: bool = False
    git_confirms: bool = False
    keyword_match: bool = False
    explanation_context: str = ""


# ---------------------------------------------------------------------------
# Verifier
# ---------------------------------------------------------------------------

class Verifier:

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def verify(
        self,
        candidate: Any,
        entry_nodes: List[str],
        graph: Any,
        incident: Any,
    ) -> VerificationResult:
        """Run all three checks on a single candidate and return a result."""
        result = VerificationResult(candidate=candidate)

        # --- Check 1: structural path ------------------------------------------
        try:
            result.path_exists = self._check_path_exists(candidate, entry_nodes, graph)
        except Exception:
            result.path_exists = False

        if result.path_exists:
            result.checks_passed.append("path_exists")
        else:
            result.checks_failed.append("path_exists")

        # --- Check 2: git recency ----------------------------------------------
        try:
            result.git_confirms = self._check_git_evidence(candidate, graph)
        except Exception:
            result.git_confirms = False

        if result.git_confirms:
            result.checks_passed.append("git_confirms")
        else:
            result.checks_failed.append("git_confirms")

        # --- Check 3: keyword alignment ----------------------------------------
        try:
            result.keyword_match = self._check_keyword_alignment(candidate, graph, incident)
        except Exception:
            result.keyword_match = False

        if result.keyword_match:
            result.checks_passed.append("keyword_match")
        else:
            result.checks_failed.append("keyword_match")

        # --- Confidence & validity ---------------------------------------------
        n_passed = len(result.checks_passed)
        if n_passed >= 3:
            result.confidence = "high"
            result.is_valid = True
        elif n_passed == 2:
            result.confidence = "medium"
            result.is_valid = True
        elif n_passed == 1:
            result.confidence = "low"
            result.is_valid = True
        else:
            result.confidence = "low"
            result.is_valid = False

        # Path existence is mandatory — override is_valid if it failed.
        if not result.path_exists:
            result.is_valid = False

        # --- Explanation context for LLM prompt --------------------------------
        node_name = getattr(candidate, "node_name", "") or ""
        file_path = getattr(candidate, "file_path", "") or ""
        git_evidence = getattr(candidate, "git_evidence", "") or ""
        reasons = getattr(candidate, "reasons", []) or []

        line_number = getattr(candidate, "line_number", 0) or 0
        location = (
            f"{file_path}:{line_number}" if line_number else file_path
        )
        result.explanation_context = (
            f"Root cause candidate: {node_name} in {location}. "
            f"Confidence: {result.confidence}. "
            f"Checks passed: {', '.join(result.checks_passed)}. "
            f"Git evidence: {git_evidence or 'none'}. "
            f"Reasons: {', '.join(reasons)}."
        )

        return result

    def verify_candidates(
        self,
        candidates: List[Any],
        entry_nodes: List[str],
        graph: Any,
        incident: Any,
        top_n: int = 3,
    ) -> List[VerificationResult]:
        """Verify the top N candidates and return results sorted by confidence."""
        results: List[VerificationResult] = []
        for candidate in (candidates or [])[:top_n]:
            try:
                vr = self.verify(candidate, entry_nodes, graph, incident)
            except Exception:
                vr = VerificationResult(candidate=candidate)
            results.append(vr)

        # Rank valid candidates by traversal score first, then confidence as a
        # tiebreak. The score already folds in git recency (weight 0.35), so
        # ranking by confidence ahead of score double-counts recency and lets a
        # coincidentally-recent, structurally-reachable node leapfrog the real,
        # higher-scored culprit. Confidence is still reported per candidate.
        results.sort(key=lambda r: (
            0 if r.is_valid else 1,
            -(getattr(r.candidate, "score", 0.0) or 0.0),
            _CONFIDENCE_RANK.get(r.confidence, 2),
        ))
        return results

    # -----------------------------------------------------------------------
    # Check 1 — structural path
    # -----------------------------------------------------------------------

    def _check_path_exists(
        self,
        candidate: Any,
        entry_nodes: List[str],
        graph: Any,
        max_hops: int = 5,
        max_nodes: int = 200,
    ) -> bool:
        """A structural path exists between the candidate and the crash site.

        Checked in BOTH directions over CALLS/IMPORTS edges:
          - candidate -> entry  (the candidate is upstream — it calls into the
            crash site), and
          - entry -> candidate  (the candidate is *downstream* — the crash site
            called into it, e.g. a callee or config that returned bad data).

        Only the first (forward-from-candidate) direction was checked
        originally, which incorrectly disqualified every downstream root cause.
        """
        try:
            start_id = getattr(candidate, "node_id", None)
            if not start_id:
                return False

            entry_set = set(entry_nodes or [])
            if start_id in entry_set:
                return True

            # Direction 1: candidate reaches an entry node (candidate upstream).
            if self._reaches(graph, [start_id], entry_set, max_hops, max_nodes):
                return True
            # Direction 2: an entry node reaches the candidate (candidate
            # downstream of the crash site).
            if self._reaches(graph, list(entry_set), {start_id}, max_hops, max_nodes):
                return True
            return False
        except Exception:
            return False

    def _reaches(
        self,
        graph: Any,
        start_ids: List[str],
        target_set: set,
        max_hops: int,
        max_nodes: int,
    ) -> bool:
        """Forward BFS over CALLS/IMPORTS from any start id to any target id."""
        q: deque = deque((sid, 0) for sid in start_ids if sid)
        visited: set = set()
        nodes_checked = 0

        while q and nodes_checked < max_nodes:
            current_id, hop = q.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            nodes_checked += 1

            if current_id in target_set:
                return True
            if hop >= max_hops:
                continue

            try:
                edges = graph.get_edges_from(current_id)
            except Exception:
                continue

            for edge in (edges or []):
                if edge.relationship in ("CALLS", "IMPORTS"):
                    if edge.target_id not in visited:
                        q.append((edge.target_id, hop + 1))

        return False

    # -----------------------------------------------------------------------
    # Check 2 — git recency
    # -----------------------------------------------------------------------

    def _check_git_evidence(
        self,
        candidate: Any,
        graph: Any,
    ) -> bool:
        """Return True if the node was modified within the last 30 days."""
        try:
            node_id = getattr(candidate, "node_id", None)
            if not node_id:
                return False

            node = graph.get_node(node_id)
            if node is None:
                return False

            meta = node.metadata if isinstance(node.metadata, dict) else {}
            days_since = days_since_iso(meta.get("last_commit_date", "") or "")
            return days_since is not None and days_since <= 30
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # Check 3 — keyword alignment
    # -----------------------------------------------------------------------

    def _check_keyword_alignment(
        self,
        candidate: Any,
        graph: Any,
        incident: Any,
    ) -> bool:
        """Return True if any incident keyword appears in the candidate's text."""
        try:
            keywords = getattr(incident, "keywords", None) or []
            if not keywords:
                return False

            node_id = getattr(candidate, "node_id", None)
            node = graph.get_node(node_id) if node_id else None

            name = ""
            docstring = ""
            commit_msg = ""
            if node is not None:
                name = node.name or ""
                docstring = node.docstring or ""
                meta = node.metadata if isinstance(node.metadata, dict) else {}
                commit_msg = meta.get("last_commit_message", "") or ""

            git_evidence = getattr(candidate, "git_evidence", "") or ""

            return bool(matched_keywords(
                keywords, name, docstring, commit_msg, git_evidence
            ))
        except Exception:
            return False


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
    from diagnosis.traversal_engine import TraversalEngine
    from semantic.tfidf_enricher import TFIDFEnricher

    if len(sys.argv) < 3:
        print("Usage: python verifier.py <pickle_path> <tfidf_path>")
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
    result = engine.traverse(entry_nodes, graph, incident)

    verifier = Verifier()
    verified = verifier.verify_candidates(
        result.candidate_root_causes,
        entry_nodes,
        graph,
        incident,
        top_n=3,
    )

    print("\n=== Verification Results ===")
    for vr in verified:
        print(f"\nCandidate: {vr.candidate.node_name} ({vr.candidate.file_path})")
        print(f"Valid:      {vr.is_valid}")
        print(f"Confidence: {vr.confidence}")
        print(f"Passed:     {vr.checks_passed}")
        print(f"Failed:     {vr.checks_failed}")
        print(f"Path:       {vr.path_exists}")
        print(f"Git:        {vr.git_confirms}")
        print(f"Keywords:   {vr.keyword_match}")
