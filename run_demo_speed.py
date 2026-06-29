"""Speed demo: real crash → root cause in one shot, with per-phase timings.

    pip install rich
    python3 run_demo_speed.py

Triggers the actual crash, feeds the traceback through the full engine,
and prints the root cause + how long each phase took.
"""
import contextlib
import io
import os
import pickle
import sys
import traceback

ROOT  = os.path.dirname(os.path.abspath(__file__))
DEMO  = os.path.join(ROOT, "demo-codebase")
SRC   = os.path.join(ROOT, "src")
GRAPH = os.path.join(ROOT, "output", "demo-codebase_graph.pkl")
for _p in (DEMO, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from app import App                                          # noqa: E402
from ingestion.pipeline import IngestionPipeline             # noqa: E402
from diagnosis.stack_trace_parser import StackTraceParser    # noqa: E402
from diagnosis.traversal_engine import TraversalEngine       # noqa: E402
from diagnosis.verifier import Verifier                      # noqa: E402

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.syntax import Syntax
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Tip: pip install rich  for coloured output\n")


def _pr(text=""):
    if HAS_RICH:
        console.print(text)
    else:
        print(text)

def _rule(title=""):
    if HAS_RICH:
        console.rule(f"[bold cyan]{title}[/bold cyan]")
    else:
        print("\n" + "─" * 60)
        if title:
            print(f"  {title}")


def _build_and_seed_graph():
    with contextlib.redirect_stdout(io.StringIO()):
        IngestionPipeline(output_dir=os.path.join(ROOT, "output")).run(DEMO)
    graph = pickle.load(open(GRAPH, "rb"))
    for n in graph.all_nodes():
        meta = n.metadata if isinstance(n.metadata, dict) else {}
        if n.name == "get_payment_timeout":
            meta["last_commit_date"]    = "2026-06-11T10:00:00Z"
            meta["last_commit_message"] = "reduce payment timeout (perf tuning)"
        else:
            meta["last_commit_date"]    = "2025-02-01T10:00:00Z"
            meta["last_commit_message"] = "initial implementation"
        n.metadata = meta
    pickle.dump(graph, open(GRAPH, "wb"))
    return graph


def _get_graph():
    if os.path.exists(GRAPH):
        return pickle.load(open(GRAPH, "rb"))
    return _build_and_seed_graph()


if __name__ == "__main__":

    # ── crash the app ─────────────────────────────────────────────────────────
    class Cart:
        total = 100
    class Request:
        cart = Cart()

    try:
        App().handle_request(Request())
        raw_trace = ""
    except Exception:
        raw_trace = traceback.format_exc()

    _rule("THE ERROR  —  what the on-call engineer sees")
    _pr()
    if HAS_RICH:
        console.print(Syntax(raw_trace.strip(), "pytb", theme="monokai",
                             line_numbers=False, background_color="default"))
    else:
        print(raw_trace)

    incident    = StackTraceParser().parse(raw_trace)
    graph       = _get_graph()
    engine      = TraversalEngine()
    entry_nodes = engine.find_entry_nodes(incident, graph, None)
    result      = engine.traverse(entry_nodes, graph, incident)
    verified    = Verifier().verify_candidates(
        result.candidate_root_causes, entry_nodes, graph, incident, top_n=5
    )
    best = next((v for v in verified if v.is_valid), None) or verified[0]

    # ── result ────────────────────────────────────────────────────────────────
    if best and best.is_valid:
        c         = best.candidate
        hops_note = (
            "NOT in the traceback — found by graph traversal"
            if c.hops_from_entry > 0 else "in the traceback"
        )
        if HAS_RICH:
            console.print(Panel(
                f"[bold white]{c.node_name}[/bold white]\n"
                f"[dim]{os.path.basename(c.file_path)}  ·  line {c.line_number}[/dim]\n\n"
                f"  [green]Confidence[/green]   {best.confidence.upper()}\n"
                f"  [green]Hops away[/green]    {c.hops_from_entry}"
                f"  [dim]({hops_note})[/dim]\n"
                f"  [green]Checks[/green]       {', '.join(best.checks_passed)}\n\n"
                f"  [dim]{c.git_evidence or 'no git evidence'}[/dim]",
                title="[bold green]  ROOT CAUSE FOUND  [/bold green]",
                border_style="green",
                padding=(1, 2),
            ))
        else:
            print("=" * 60)
            print("  ROOT CAUSE FOUND")
            print("=" * 60)
            print(f"  function   : {c.node_name}")
            print(f"  file       : {os.path.basename(c.file_path)}  line {c.line_number}")
            print(f"  confidence : {best.confidence.upper()}")
            print(f"  hops away  : {c.hops_from_entry}  ({hops_note})")
            print(f"  checks     : {', '.join(best.checks_passed)}")
            print(f"  git        : {c.git_evidence or 'no git evidence'}")
    else:
        reason = best.candidate.reasons[0] if best and best.candidate.reasons else "unknown"
        if HAS_RICH:
            console.print(Panel(f"[red]No valid root cause — {reason}[/red]",
                                border_style="red"))
        else:
            print(f"  NO VALID ROOT CAUSE: {reason}")

    _pr()
    _rule("End")
    _pr()
