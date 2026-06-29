"""Shared, LLM-free diagnosis service used by both demos.

Wraps the deterministic knowledge-graph pipeline
(StackTraceParser -> TraversalEngine -> Verifier) into a single
`diagnose(trace, graph_key)` call that returns a JSON-serialisable dict.

Multiple graphs are supported via the GRAPHS registry.  Pass `graph_key`
to target a specific graph; omit it to use the default (demo-codebase).
"""
import os
import pickle
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "src")
DEMO = os.path.join(ROOT, "demo-codebase")
for _p in (SRC, DEMO, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from diagnosis.stack_trace_parser import StackTraceParser   # noqa: E402
from diagnosis.traversal_engine import TraversalEngine       # noqa: E402
from diagnosis.verifier import Verifier                      # noqa: E402
from semantic.tfidf_enricher import TFIDFEnricher            # noqa: E402
from demo_app.sample_traces import PRESETS                   # noqa: E402
from tf_traces import TF_PRESETS                             # noqa: E402
from merged_traces import MERGED_PRESETS                     # noqa: E402

_CONF_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}

# ── Graph registry ────────────────────────────────────────────────────────────
GRAPHS = {
    "demo-codebase": {
        "label":   "Demo Codebase",
        "pkl":     os.path.join(ROOT, "output", "demo-codebase_graph.pkl"),
        "tfidf":   os.path.join(ROOT, "output", "demo-codebase_tfidf.json"),
        "presets": PRESETS,
        "seed":    True,
    },
    "tensorflow": {
        "label":   "TensorFlow (python/ops)",
        "pkl":     os.path.join(ROOT, "output", "ops_graph.pkl"),
        "tfidf":   None,
        "presets": TF_PRESETS,
        "seed":    False,
    },
    "merged": {
        "label":   "Merged (flask + werkzeug + jinja)",
        "pkl":     os.path.join(ROOT, "output", "merged_graph.pkl"),
        "tfidf":   os.path.join(ROOT, "output", "merged_tfidf.json"),
        "presets": MERGED_PRESETS,
        "seed":    False,
    },
}
DEFAULT_GRAPH = "demo-codebase"

# ── Seeding helpers (demo-codebase only) ──────────────────────────────────────
_DEFAULT_SEED = ("get_payment_timeout", "2026-06-11T10:00:00Z", "reduce payment timeout (perf tuning)")


def _seed_git_metadata(graph, seed_node, seed_date, seed_msg):
    for n in graph.all_nodes():
        meta = n.metadata if isinstance(n.metadata, dict) else {}
        if seed_node and n.name == seed_node:
            meta["last_commit_date"]    = seed_date
            meta["last_commit_message"] = seed_msg
        else:
            meta["last_commit_date"]    = "2025-02-01T10:00:00Z"
            meta["last_commit_message"] = "initial implementation"
        n.metadata = meta
    return graph


def _load_graph(trace_text="", graph_key=DEFAULT_GRAPH):
    cfg = GRAPHS.get(graph_key) or GRAPHS[DEFAULT_GRAPH]
    graph = pickle.load(open(cfg["pkl"], "rb"))
    if not cfg["seed"]:
        return graph
    for preset in cfg["presets"].values():
        t = preset.get("trace", "")
        if t.strip() in trace_text.strip() or trace_text.strip() in t.strip():
            return _seed_git_metadata(graph, preset["seed_node"], preset["seed_date"], preset["seed_msg"])
    node, date, msg = _DEFAULT_SEED
    return _seed_git_metadata(graph, node, date, msg)


# ── Enricher cache (lazy, one per graph) ─────────────────────────────────────
_ENRICHERS: dict = {}


def _get_enricher(graph_key):
    if graph_key not in _ENRICHERS:
        tfidf_path = (GRAPHS.get(graph_key) or {}).get("tfidf")
        if tfidf_path and os.path.exists(tfidf_path):
            _ENRICHERS[graph_key] = TFIDFEnricher.load(tfidf_path)
        else:
            _ENRICHERS[graph_key] = None
    return _ENRICHERS[graph_key]


# ── Shared pipeline objects ───────────────────────────────────────────────────
_PARSER   = StackTraceParser()
_ENGINE   = TraversalEngine()
_VERIFIER = Verifier()


# ── Public API ────────────────────────────────────────────────────────────────

def list_graphs():
    """Return metadata for every registered graph (used to populate the dropdown)."""
    result = {}
    for key, cfg in GRAPHS.items():
        try:
            g = pickle.load(open(cfg["pkl"], "rb"))
            presets = [{"key": k, "label": v["label"], "trace": v["trace"]}
                       for k, v in cfg["presets"].items()]
            result[key] = {
                "label":   cfg["label"],
                "nodes":   g.node_count,
                "edges":   g.edge_count,
                "file":    os.path.basename(cfg["pkl"]),
                "presets": presets,
            }
        except Exception:
            pass
    return result


def graph_stats(graph_key=DEFAULT_GRAPH):
    cfg = GRAPHS.get(graph_key) or GRAPHS[DEFAULT_GRAPH]
    try:
        g = pickle.load(open(cfg["pkl"], "rb"))
        return {"nodes": g.node_count, "edges": g.edge_count,
                "graph_file": os.path.basename(cfg["pkl"]), "label": cfg["label"]}
    except Exception:
        return {"nodes": 0, "edges": 0, "graph_file": cfg["pkl"], "label": cfg["label"]}


def _candidate_dict(v):
    c = v.candidate
    return {
        "node_name":       c.node_name,
        "file":            os.path.basename(c.file_path),
        "file_path":       c.file_path,
        "line_number":     c.line_number,
        "node_type":       c.node_type,
        "score":           round(c.score, 3),
        "hops_from_entry": c.hops_from_entry,
        "in_traceback":    c.hops_from_entry == 0,
        "is_valid":        v.is_valid,
        "confidence":      v.confidence,
        "checks_passed":   list(v.checks_passed),
        "checks_failed":   list(v.checks_failed),
        "git_evidence":    c.git_evidence,
        "reasons":         list(c.reasons),
    }


def _build_subgraph(entry_ids, traversal_ids, candidates, headline, graph):
    """Return nodes+edges of the visited subgraph for D3 visualisation."""
    entry_set  = set(entry_ids)
    root_name  = headline["node_name"] if headline else None
    hop_map    = {c["node_name"]: c["hops_from_entry"] for c in candidates}

    key_ids = list(dict.fromkeys(list(entry_ids) + list(traversal_ids)))[:40]
    node_id_set = set(key_ids)

    nodes_out = []
    for nid in key_ids:
        n = graph.get_node(nid)
        if not n:
            continue
        role = ("root_cause" if (root_name and n.name == root_name)
                else "entry" if nid in entry_set
                else "traversal")
        nodes_out.append({
            "id":   nid,
            "name": n.name or "",
            "file": os.path.basename(n.file_path or ""),
            "type": n.type or "function",
            "role": role,
            "hop":  hop_map.get(n.name, 0 if nid in entry_set else 1),
        })

    edges_out, seen = [], set()
    for nid in node_id_set:
        try:
            for edge in graph.get_edges_from(nid):
                if edge.target_id in node_id_set:
                    k = (nid, edge.target_id)
                    if k not in seen:
                        seen.add(k)
                        edges_out.append({"source": nid, "target": edge.target_id,
                                          "rel": edge.relationship})
        except Exception:
            pass

    return {"nodes": nodes_out, "edges": edges_out}


def diagnose(raw_trace, graph_key=DEFAULT_GRAPH, top_n=10):
    """Run the full LLM-free pipeline on a stacktrace string."""
    graph    = _load_graph(raw_trace, graph_key)
    enricher = _get_enricher(graph_key)

    t0 = time.perf_counter()
    timings = {}

    incident = _PARSER.parse(raw_trace)
    timings["parse_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    t1 = time.perf_counter()
    entry_nodes = _ENGINE.find_entry_nodes(incident, graph, enricher)
    timings["entry_ms"] = round((time.perf_counter() - t1) * 1000, 2)

    t2 = time.perf_counter()
    result = _ENGINE.traverse(entry_nodes, graph, incident)
    timings["traverse_ms"] = round((time.perf_counter() - t2) * 1000, 2)

    t3 = time.perf_counter()
    verified = _VERIFIER.verify_candidates(
        result.candidate_root_causes, entry_nodes, graph, incident, top_n=top_n
    )
    timings["verify_ms"] = round((time.perf_counter() - t3) * 1000, 2)
    timings["total_ms"]  = round((time.perf_counter() - t0) * 1000, 2)

    candidates = [_candidate_dict(v) for v in verified]

    valid = [v for v in verified if v.is_valid]
    best  = max(valid, key=lambda v: (_CONF_RANK.get(v.confidence, 0), v.candidate.score)) if valid else None
    headline = _candidate_dict(best) if best else None

    def _short(node_id):
        parts = node_id.split("::")
        fname = os.path.basename(parts[0])
        tail  = parts[-1] or (parts[-2] if len(parts) > 1 else "")
        return f"{fname}::{tail}" if tail else fname

    return {
        "is_valid":        headline is not None,
        "graph_key":       graph_key,
        "incident": {
            "error_type":    incident.error_type,
            "error_message": incident.error_message,
            "language":      incident.language,
            "keywords":      list(incident.keywords),
            "frames": [
                {"file":     os.path.basename(getattr(f, "file_path", "") or ""),
                 "function": getattr(f, "function", "") or getattr(f, "function_name", ""),
                 "line":     getattr(f, "line_number", None)}
                for f in incident.frames
            ],
        },
        "headline":           headline,
        "candidates":         candidates,
        "entry_nodes":        [_short(n) for n in entry_nodes],
        "traversal_path":     [_short(n) for n in result.traversal_path],
        "nodes_visited":      len(result.visited_nodes),
        "subgraph":           _build_subgraph(entry_nodes, result.traversal_path,
                                              candidates, headline, graph),
        "candidates_found":   len(result.candidate_root_causes),
        "hops_completed":     result.hops_completed,
        "timings":            timings,
        "no_result_reason":   None if headline else "No candidate passed verification.",
    }
