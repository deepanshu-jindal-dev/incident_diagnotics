#!/usr/bin/env python3
"""CLI entry point for the Incident Diagnostics Engine.

Loads a pre-built knowledge graph (and optionally a TF-IDF index),
parses a stack trace or natural-language incident, runs the full
diagnosis pipeline via `IncidentEngine`, and prints a human-readable
root-cause report.

Usage:

    PYTHONPATH=src python3 src/diagnose.py \\
        --graph <path_to_graph.pkl> \\
        --trace <path_to_trace.txt_OR_raw_trace_string> \\
        [--tfidf <path_to_tfidf.json>] \\
        [--hops 4] \\
        [--top 5]
"""

import argparse
import os
import pickle
import sys
import time

# Make `src/` importable whether invoked as `python3 src/diagnose.py` or
# with PYTHONPATH=src, so the absolute package imports below resolve.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from diagnosis.incident_engine import IncidentEngine          # noqa: E402
from diagnosis.stack_trace_parser import StackTraceParser     # noqa: E402
from semantic.tfidf_enricher import TFIDFEnricher             # noqa: E402


_SEP = "=" * 31


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="diagnose.py",
        description="Diagnose a production incident against a code knowledge graph.",
    )
    parser.add_argument("--graph", required=True,
                        help="path to graph pickle file")
    parser.add_argument("--trace", required=True,
                        help="path to a .txt trace file, or a raw trace string")
    parser.add_argument("--tfidf", default=None,
                        help="path to TF-IDF index (omit to run without semantic search)")
    parser.add_argument("--hops", type=int, default=4,
                        help="max traversal hops (default 4)")
    parser.add_argument("--top", type=int, default=5,
                        help="top N candidates to verify (default 5)")
    return parser.parse_args()


def _load_trace(trace_arg: str) -> str:
    """A `.txt` argument is read from disk; anything else is treated as
    a raw trace string passed directly on the command line."""
    if trace_arg.endswith(".txt"):
        with open(trace_arg, "r", encoding="utf-8") as fh:
            return fh.read()
    return trace_arg


def _print_report(report, incident) -> None:
    """Print the fixed-format diagnosis output. The Incident block is
    sourced from the parsed `incident`; the Pipeline and Diagnosis
    blocks from the `DiagnosisReport`."""
    print("=== Incident Diagnostics Engine ===")
    print()
    print("Incident:")
    print("  error_type:    " + (incident.error_type or ""))
    print("  error_message: " + (incident.error_message or ""))
    print("  keywords:      " + str(incident.keywords))
    print("  frames:        " + str(len(incident.frames)))
    print()
    print("Pipeline:")
    print("  entry nodes found: " + str(report.entry_nodes_found))
    print("  candidates found:  " + str(report.candidates_found))
    print("  nodes visited:     " + str(report.nodes_visited))
    print()
    print(_SEP)
    print("DIAGNOSIS")
    print(_SEP)
    print()
    print("  Root cause:    " + (report.root_cause_node or "") +
          "  (" + (report.root_cause_file or "") + ")")
    print("  Confidence:    " + report.confidence)
    print("  Checks passed: " + str(report.checks_passed))
    print("  Checks failed: " + str(report.checks_failed))
    print("  Hops from entry: " + str(report.hops_from_entry))
    print()
    print("  Reasons:")
    for reason in report.reasons:
        print("    - " + reason)
    print()
    print("  Git evidence: " + (report.git_evidence or "none"))
    print()
    print(_SEP)
    if report.is_valid:
        print("  Root cause identified with " + report.confidence.upper() + " confidence.")
        print("  Inspect " + (report.root_cause_node or "") +
              " in " + (report.root_cause_file or "") + ".")
    else:
        print("  No root cause confirmed.")
        print("  Reason: " + (report.no_result_reason or ""))
    print(_SEP)


def main() -> None:
    args = _parse_args()
    start = time.time()

    try:
        # ── Load graph ────────────────────────────────────────────────
        try:
            with open(args.graph, "rb") as fh:
                graph = pickle.load(fh)
        except Exception:
            print("Error: could not load graph from " + args.graph)
            sys.exit(1)

        # ── Load trace (file or raw string) ───────────────────────────
        raw_trace = _load_trace(args.trace)
        if not raw_trace or not raw_trace.strip():
            print("Error: empty stack trace")
            sys.exit(1)

        # ── Load enricher (optional) ──────────────────────────────────
        enricher = TFIDFEnricher.load(args.tfidf) if args.tfidf else None

        # ── Parse trace for the Incident block (frame count, etc.) ────
        incident = StackTraceParser().parse(raw_trace)

        # ── Run the full diagnosis pipeline ───────────────────────────
        report = IncidentEngine().diagnose(
            raw_trace, graph, enricher,
            max_hops=args.hops, top_n=args.top,
        )

        # ── Output ────────────────────────────────────────────────────
        _print_report(report, incident)

        print()
        print("Completed in {:.2f}s".format(time.time() - start))

    except SystemExit:
        # Propagate explicit exit codes from the guards above unchanged.
        raise
    except Exception as ex:
        print("Error: " + str(ex))
        sys.exit(1)


if __name__ == "__main__":
    main()
