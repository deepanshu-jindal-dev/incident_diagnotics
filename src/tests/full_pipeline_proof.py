"""End-to-end proof run — narrates every stage with timing.

Runs the WHOLE flow on the real Flask / Werkzeug / Jinja repos and prints,
step by step, how long each stage takes:

    acquire repos → build graph → save pickle → load pickle →
    build TF-IDF index → diagnose a real incident (full result)

    python src/tests/full_pipeline_proof.py

Uses the cached clones under output/clones (no network). The final stage feeds
a real Flask→Jinja TemplateNotFound traceback through the engine and prints the
diagnosed root cause — proof the full pipeline works, not just the timings.
"""

import contextlib
import io
import os
import pickle
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.dirname(_HERE)
_ROOT = os.path.dirname(_SRC)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from graph.graph import Graph                              # noqa: E402
from ingestion.pipeline import IngestionPipeline           # noqa: E402
from semantic.tfidf_enricher import TFIDFEnricher          # noqa: E402
from diagnosis.incident_engine import IncidentEngine       # noqa: E402

_REPOS = [
    "https://github.com/pallets/flask",
    "https://github.com/pallets/werkzeug",
    "https://github.com/pallets/jinja",
]

# Real Flask → Jinja → loaders TemplateNotFound traceback (test case TC3).
_TRACE = """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 982, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File "/output/clones/flask/src/flask/templating.py", line 148, in render_template
    return _render(ctx, t, ctx_dict)
  File "/output/clones/flask/src/flask/templating.py", line 135, in _render
    rv = template.render(context)
  File "/output/clones/jinja/src/jinja2/environment.py", line 999, in get_template
    return self._load_template(name, globals)
  File "/output/clones/jinja/src/jinja2/loaders.py", line 215, in get_source
    raise TemplateNotFound(template)
jinja2.exceptions.TemplateNotFound: dashboard.html
"""


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _hr():
    print("-" * 60)


def main():
    out_dir = os.path.join(_ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    pipe = IngestionPipeline(output_dir=out_dir)
    grand_start = time.perf_counter()

    print("=" * 60)
    print("  FULL PIPELINE PROOF  —  Flask · Werkzeug · Jinja")
    print("=" * 60)

    # STEP 1 — acquire repositories (cached clones) -----------------------
    print("\n[1] Acquiring repositories (cached clones, no network)")
    _hr()
    src_dirs = []
    for url in _REPOS:
        name = url.rstrip("/").split("/")[-1]
        t0 = time.perf_counter()
        src_dir, _root = _quiet(pipe._clone_and_detect, url)
        dt = time.perf_counter() - t0
        n = len(_quiet(pipe._discover_files, src_dir))
        src_dirs.append(src_dir)
        print("    {:<10} ready in {:6.2f} s   ({} source files)".format(name, dt, n))

    files = []
    for d in src_dirs:
        files.extend(_quiet(pipe._discover_files, d))

    # STEP 2 — build the merged graph -------------------------------------
    print("\n[2] Building merged knowledge graph from {} files".format(len(files)))
    _hr()
    t0 = time.perf_counter()
    graph = Graph()
    for f in files:
        _quiet(pipe._process_file, f, graph)
    parse_dt = time.perf_counter() - t0
    print("    parsed all files          {:6.2f} s".format(parse_dt))

    t0 = time.perf_counter()
    _quiet(pipe._resolve, graph)
    resolve_dt = time.perf_counter() - t0
    print("    entity resolution         {:6.2f} s".format(resolve_dt))
    print("    => {:,} nodes · {:,} edges   (built in {:.2f} s total)".format(
        graph.node_count, graph.edge_count, parse_dt + resolve_dt))

    # STEP 3 — persist + reload -------------------------------------------
    print("\n[3] Persisting and reloading the graph")
    _hr()
    pkl = os.path.join(out_dir, "proof_graph.pkl")
    t0 = time.perf_counter()
    with open(pkl, "wb") as fh:
        pickle.dump(graph, fh)
    save_dt = time.perf_counter() - t0
    size_mb = os.path.getsize(pkl) / (1024 * 1024)
    print("    save → pickle           {:5d} ms   ({:.1f} MB on disk)".format(
        round(save_dt * 1000), size_mb))

    t0 = time.perf_counter()
    with open(pkl, "rb") as fh:
        graph = pickle.load(fh)
    load_dt = time.perf_counter() - t0
    print("    load ← pickle           {:5d} ms".format(round(load_dt * 1000)))

    # STEP 4 — TF-IDF index -----------------------------------------------
    print("\n[4] Building TF-IDF semantic index")
    _hr()
    t0 = time.perf_counter()
    _quiet(TFIDFEnricher().enrich, graph)
    tfidf_dt = time.perf_counter() - t0
    print("    indexed {:,} nodes        {:5d} ms".format(
        graph.node_count, round(tfidf_dt * 1000)))

    # STEP 5 — diagnose a real incident -----------------------------------
    print("\n[5] Diagnosing a real incident")
    _hr()
    print("    Incident: jinja2.exceptions.TemplateNotFound: dashboard.html")
    print("    (propagates flask.app → flask.templating → jinja2 → loaders.py)")
    t0 = time.perf_counter()
    report = IncidentEngine().diagnose(_TRACE, graph)
    diag_dt = time.perf_counter() - t0
    print("    diagnosed in            {:5d} ms".format(round(diag_dt * 1000)))
    print()
    print("    error type    : {}".format(report.error_type))
    print("    entry nodes   : {}   nodes visited: {}".format(
        report.entry_nodes_found, report.nodes_visited))
    if report.is_valid:
        print("    ROOT CAUSE    : {}   ({})".format(
            report.root_cause_node, os.path.basename(report.root_cause_file)))
        print("    hops away     : {}   (0 = in the trace; >0 = NOT in the trace)".format(
            report.hops_from_entry))
        print("    confidence    : {}".format(report.confidence.upper()))
        print("    checks passed : {}".format(report.checks_passed))
    else:
        print("    NO VALID ROOT CAUSE: {}".format(report.no_result_reason))

    print("\n" + "=" * 60)
    print("  DONE — full pipeline ran in {:.2f} s".format(
        time.perf_counter() - grand_start))
    print("=" * 60)


if __name__ == "__main__":
    main()
