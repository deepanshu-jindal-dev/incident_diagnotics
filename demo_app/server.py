"""Demo — no-LLM root-cause UI with multi-graph support.

    pip install flask
    python3 demo_app/server.py
    open http://127.0.0.1:5000
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template, request

from demo_app.diagnose_service import DEFAULT_GRAPH, GRAPHS, diagnose, list_graphs
from demo_app.sample_traces import PRIMARY_TRACE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo-codebase")
HAIKU_MODEL = "claude-haiku-4-5-20251001"

app = Flask(__name__, template_folder=os.path.join(os.path.dirname(__file__), "templates"))

_GRAPHS_CACHE = None


def _get_graphs():
    global _GRAPHS_CACHE
    if _GRAPHS_CACHE is None:
        _GRAPHS_CACHE = list_graphs()
    return _GRAPHS_CACHE


# ── LLM comparison helpers ────────────────────────────────────────────────────

def _call_haiku(prompt: str):
    """Call Claude Haiku via the claude CLI. Returns (text, seconds)."""
    workdir = tempfile.mkdtemp(prefix="haiku_compare_")
    try:
        t0 = time.perf_counter()
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", HAIKU_MODEL],
            cwd=workdir, capture_output=True, text=True, timeout=120,
        )
        dt = time.perf_counter() - t0
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[:300])
        return proc.stdout.strip(), round(dt, 1)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _read_file_safe(path: str, max_chars: int = 3000) -> str:
    try:
        text = open(path).read()
        return text[:max_chars] + ("\n…(truncated)" if len(text) > max_chars else "")
    except Exception:
        return ""


def _files_in_trace(trace: str, graph_key: str) -> list:
    """Return local paths of files that literally appear in the traceback."""
    seen, paths = set(), []
    for line in trace.splitlines():
        m = re.search(r'File "([^"]+\.py)"', line)
        if not m:
            continue
        raw = m.group(1)
        if raw in seen:
            continue
        seen.add(raw)
        # demo-codebase traces use the absolute DEMO path
        candidate = raw if os.path.exists(raw) else os.path.join(DEMO, os.path.basename(raw))
        if os.path.exists(candidate):
            paths.append(candidate)
    return paths


def _get_source_context(trace: str, graph_key: str) -> str:
    """Only files that literally appear in the traceback — no off-trace leakage."""
    sources = []
    for fpath in _files_in_trace(trace, graph_key)[:6]:
        content = _read_file_safe(fpath, max_chars=2000)
        if content:
            sources.append(f"--- {os.path.basename(fpath)} ---\n{content}")
    return "\n\n".join(sources)


def _get_offtrace_sources(report: dict, graph_key: str, trace: str) -> str:
    """Files the engine surfaced that do NOT appear in the traceback.
    Only used in the tool prompt — never in the naked prompt.
    """
    in_trace = {os.path.basename(p) for p in _files_in_trace(trace, graph_key)}
    seen, sources = set(), []
    for short in report.get("traversal_path", []):
        fname = short.split("::")[0]
        if not fname or fname in in_trace or fname in seen:
            continue
        seen.add(fname)
        candidate = os.path.join(DEMO, fname)
        if os.path.exists(candidate):
            content = _read_file_safe(candidate, max_chars=1500)
            if content:
                sources.append(f"--- {fname} (off-trace, surfaced by graph engine) ---\n{content}")
        if len(sources) >= 3:
            break
    return "\n\n".join(sources)


_ASK = (
    "Identify the ROOT CAUSE of this production error. Reply in ≤4 lines:\n"
    "  ROOT CAUSE: <file>::<function> — <one-line why>\n"
    "  FIX: <what to change>\n"
    "Answer directly from the information given; do not use any tools."
)


def _naked_prompt(trace: str, sources: str) -> str:
    src_block = f"\n\nSource of the files that appear in the stacktrace:\n\n{sources}" if sources else ""
    return f"A production service crashed. Here is the stacktrace:\n\n{trace}{src_block}\n\n{_ASK}"


def _tool_prompt(trace: str, sources: str, offtrace: str, report: dict) -> str:
    h = report.get("headline") or {}
    path = " → ".join(report.get("traversal_path", [])[:8])
    tool_block = (
        "ROOT-CAUSE ENGINE OUTPUT (deterministic knowledge-graph, no LLM):\n"
        f"  root cause : {h.get('node_name','?')}  ({h.get('file','?')}:{h.get('line_number','?')})\n"
        f"  confidence : {(h.get('confidence') or '?').upper()}  "
        f"checks passed: {', '.join(h.get('checks_passed', []))}\n"
        f"  hops upstream of crash : {h.get('hops_from_entry','?')}  "
        f"({'NOT in stacktrace' if not h.get('in_traceback') else 'in stacktrace'})\n"
        f"  git evidence : {h.get('git_evidence') or 'none'}\n"
        f"  call path    : {path}"
    )
    src_block      = f"\n\nSource of the files in the stacktrace:\n\n{sources}" if sources else ""
    offtrace_block = (f"\n\nFiles on the engine's call path that do NOT appear in the "
                      f"stacktrace:\n\n{offtrace}") if offtrace else ""
    return (f"A production service crashed. Here is the stacktrace:\n\n{trace}"
            f"{src_block}{offtrace_block}\n\n{tool_block}\n\n{_ASK}")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template(
        "index.html",
        default_trace=PRIMARY_TRACE,
        graphs=_get_graphs(),
        default_graph=DEFAULT_GRAPH,
    )


@app.route("/api/diagnose", methods=["POST"])
def api_diagnose():
    body      = request.get_json(silent=True) or {}
    trace     = body.get("trace", "")
    graph_key = body.get("graph_key", DEFAULT_GRAPH)
    if not trace.strip():
        return jsonify({"is_valid": False, "no_result_reason": "Empty stacktrace."}), 400
    return jsonify(diagnose(trace, graph_key=graph_key))


@app.route("/api/compare", methods=["POST"])
def api_compare():
    body      = request.get_json(silent=True) or {}
    trace     = body.get("trace", "")
    graph_key = body.get("graph_key", DEFAULT_GRAPH)

    if not trace.strip():
        return jsonify({"error": "Empty stacktrace."}), 400

    engine_result = diagnose(trace, graph_key=graph_key)

    if not shutil.which("claude"):
        return jsonify({
            "engine":          engine_result,
            "haiku_available": False,
            "error": "claude CLI not found — install Claude Code to enable LLM comparison.",
        })

    # naked gets ONLY files that appear in the traceback
    sources  = _get_source_context(trace, graph_key)
    # tool gets those files PLUS off-trace files the engine surfaced
    offtrace = _get_offtrace_sources(engine_result, graph_key, trace)

    try:
        ans_naked, t_naked = _call_haiku(_naked_prompt(trace, sources))
    except Exception as e:
        ans_naked, t_naked = f"Haiku call failed: {e}", 0.0

    try:
        ans_tool, t_tool = _call_haiku(_tool_prompt(trace, sources, offtrace, engine_result))
    except Exception as e:
        ans_tool, t_tool = f"Haiku call failed: {e}", 0.0

    return jsonify({
        "engine":          engine_result,
        "haiku_available": True,
        "naked":     {"answer": ans_naked, "seconds": t_naked},
        "with_tool": {"answer": ans_tool,  "seconds": t_tool},
    })


@app.route("/api/graphs")
def api_graphs():
    return jsonify(_get_graphs())


if __name__ == "__main__":
    graphs = _get_graphs()
    print("\n  No-LLM Incident Diagnostics  —  http://127.0.0.1:5000")
    for key, info in graphs.items():
        print(f"  {key}: {info['nodes']} nodes · {info['edges']} edges")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False)
