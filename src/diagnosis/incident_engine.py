"""Incident diagnosis orchestrator.

Wires the four diagnosis phases — parse → find entry nodes → traverse →
verify — into a single `diagnose()` call that returns a flat
`DiagnosisReport`. This module performs no LLM calls and no I/O: it is
pure orchestration over the existing diagnosis components.

CLI lives elsewhere (diagnose.py); this file is import-only.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional

from .stack_trace_parser import StackTraceParser
from .traversal_engine import TraversalEngine
from .verifier import Verifier


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------

@dataclass
class DiagnosisReport:
    # --- Incident info ---
    error_type: str = ""
    error_message: str = ""
    keywords: List[str] = field(default_factory=list)

    # --- Result ---
    root_cause_node: str = ""                # node name of best candidate
    root_cause_file: str = ""                # file path of best candidate
    confidence: str = "none"                 # "high" | "medium" | "low" | "none"
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    is_valid: bool = False

    # --- Evidence ---
    hops_from_entry: int = 0
    git_evidence: str = ""
    reasons: List[str] = field(default_factory=list)

    # --- Pipeline internals ---
    entry_nodes_found: int = 0
    candidates_found: int = 0
    nodes_visited: int = 0
    traversal_path: List[str] = field(default_factory=list)

    # --- Failure info ---
    no_result_reason: str = ""               # set when is_valid=False

    # --- Explanation context (for future LLM use) ---
    explanation_context: str = ""            # copied from best VerificationResult


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class IncidentEngine:
    """Run the full parse → entry → traverse → verify pipeline in one call."""

    def diagnose(
        self,
        raw_trace: str,
        graph: Any,
        enricher: Any = None,        # TFIDFEnricher, optional
        max_hops: int = 4,
        top_n: int = 5,
    ) -> DiagnosisReport:
        """Diagnose one incident end-to-end. Never raises — any failure is
        returned as a report with is_valid=False and no_result_reason set."""
        report = DiagnosisReport()
        try:
            # ── Phase 1 — parse the raw trace into a ParsedIncident ──────
            incident = StackTraceParser().parse(raw_trace)
            report.error_type = incident.error_type or ""
            report.error_message = incident.error_message or ""
            report.keywords = list(incident.keywords or [])

            engine = TraversalEngine()

            # ── Phase 2 — locate entry nodes in the graph ───────────────
            entry_nodes = engine.find_entry_nodes(incident, graph, enricher)
            report.entry_nodes_found = len(entry_nodes)

            # Case 1 — no entry nodes: the crash site is not in the graph.
            if not entry_nodes:
                report.is_valid = False
                report.confidence = "none"
                report.no_result_reason = self._crash_site_missing_reason(incident)
                return report

            # ── Phase 3 — backward BFS traversal for root-cause candidates ─
            result = engine.traverse(entry_nodes, graph, incident, max_hops)
            report.nodes_visited = len(result.visited_nodes)
            report.traversal_path = list(result.traversal_path)
            candidates = result.candidate_root_causes or []
            report.candidates_found = len(candidates)

            # Defensive: entry nodes existed but traversal yielded nothing.
            if not candidates:
                report.is_valid = False
                report.confidence = "none"
                report.no_result_reason = "Traversal produced no candidate nodes"
                return report

            # ── Phase 4 — verify the top candidates ─────────────────────
            verified = Verifier().verify_candidates(
                candidates, entry_nodes, graph, incident, top_n
            )
            best = verified[0] if verified else None

            # Case 3 — a verified, valid root cause was found.
            if best is not None and best.is_valid:
                self._populate_from_verification(report, best)
                return report

            # Case 2 — entry nodes found, but nothing passed verification.
            # Surface the highest-scoring candidate as an unverified guess.
            report.is_valid = False
            report.no_result_reason = "All candidates failed verification"

            best_guess = candidates[0]   # candidate_root_causes is score-sorted desc
            self._populate_from_candidate(report, best_guess)

            # Attach the verification detail for that guess if we have it.
            vr = self._verification_for(verified, best_guess.node_id)
            if vr is not None:
                report.checks_passed = list(vr.checks_passed)
                report.checks_failed = list(vr.checks_failed)
                report.confidence = vr.confidence or "none"
                report.explanation_context = vr.explanation_context or ""
            return report

        except Exception as ex:
            # ── Never crash — return a failure report carrying the error ─
            report.is_valid = False
            report.confidence = "none"
            report.no_result_reason = "diagnose() failed: " + repr(ex)
            return report

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _crash_site_missing_reason(self, incident: Any) -> str:
        """Build the Case-1 failure message from the incident's frame names."""
        names = [
            f.function_name
            for f in (getattr(incident, "frames", None) or [])
            if getattr(f, "function_name", "")
        ]
        joined = ", ".join(names) if names else "none extracted from trace"
        return "Crash site not found in graph. Functions searched: " + joined

    def _populate_from_verification(self, report: DiagnosisReport, vr: Any) -> None:
        """Case 3 — fill every result field from a valid VerificationResult."""
        self._populate_from_candidate(report, getattr(vr, "candidate", None))
        report.is_valid = True
        report.confidence = vr.confidence or "low"
        report.checks_passed = list(vr.checks_passed)
        report.checks_failed = list(vr.checks_failed)
        report.explanation_context = vr.explanation_context or ""

    def _populate_from_candidate(self, report: DiagnosisReport, cand: Any) -> None:
        """Copy the node/evidence fields shared by Case 2 and Case 3."""
        if cand is None:
            return
        report.root_cause_node = getattr(cand, "node_name", "") or ""
        report.root_cause_file = getattr(cand, "file_path", "") or ""
        report.hops_from_entry = getattr(cand, "hops_from_entry", 0) or 0
        report.git_evidence = getattr(cand, "git_evidence", "") or ""
        report.reasons = list(getattr(cand, "reasons", []) or [])

    def _verification_for(self, verified: List[Any], node_id: str) -> Optional[Any]:
        """Find the VerificationResult whose candidate matches node_id."""
        for vr in (verified or []):
            cand = getattr(vr, "candidate", None)
            if cand is not None and getattr(cand, "node_id", None) == node_id:
                return vr
        return None
