"""Demo: trigger a real crash, show it, then diagnose it interactively.

    pip install rich
    python3 run_demo.py

Step 1 runs the app, which crashes in PaymentService.charge ("cart is None")
and prints the real traceback an on-call engineer would see.
Step 2 walks through the diagnosis phase by phase — press Enter to advance.
The engine traces the crash 3 hops downstream to config.get_payment_timeout()
which never appears in the traceback itself.
"""
import contextlib
import io
import os
import pickle
import sys
import time
import traceback
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(ROOT, "demo-codebase")
SRC  = os.path.join(ROOT, "src")
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
    from rich.table import Table
    from rich.syntax import Syntax
    from rich import box
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    print("Tip: pip install rich  for coloured output\n")


# ── helpers ───────────────────────────────────────────────────────────────────

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

def _wait(label="Press Enter to continue"):
    if HAS_RICH:
        console.print(f"\n  [dim italic]{label} ...[/dim italic]", end="")
    else:
        print(f"\n  {label} ...", end="")
    input()
    _pr()


# ── graph helpers ─────────────────────────────────────────────────────────────

class Cart:
    total = 100

class Request:
    cart = Cart()


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
    _pr("  [dim](first run — building the knowledge graph once...)[/dim]" if HAS_RICH
        else "  (first run — building the knowledge graph once...)")
    return _build_and_seed_graph()


# ── main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    # ── STEP 1: run the app and show the crash ────────────────────────────────
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

    _wait("Press Enter to start diagnosis")

    # ── STEP 2: PHASE 1 — parse the traceback ─────────────────────────────────
    _rule("Phase 1 · Parse the Traceback")
    _pr()

    incident = StackTraceParser().parse(raw_trace)

    if HAS_RICH:
        tbl = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        tbl.add_column(style="dim", width=14)
        tbl.add_column()
        tbl.add_row("Error type", f"[red bold]{incident.error_type}[/red bold]")
        tbl.add_row("Message",    f"[dim]{incident.error_message[:80]}[/dim]")
        tbl.add_row("Frames",     str(len(incident.frames)))
        console.print(tbl)
        _pr()
        for frame in incident.frames:
            console.print(
                f"  [green]→[/green]  [bold]{frame.function_name:<28}[/bold]"
                f"  [dim]{os.path.basename(frame.file_path or '')}[/dim]"
            )
    else:
        print(f"  error type : {incident.error_type}")
        print(f"  frames     : {len(incident.frames)}")
        for frame in incident.frames:
            print(f"    → {frame.function_name:<28}  {os.path.basename(frame.file_path or '')}")

    _wait()

    # ── STEP 2: PHASE 2 — load graph + find entry nodes ───────────────────────
    _rule("Phase 2 · Load Graph  +  Locate Entry Nodes")
    _pr()

    graph = _get_graph()

    if HAS_RICH:
        console.print(f"  Graph loaded: [cyan]{graph.node_count:,}[/cyan] nodes"
                      f"  ·  [cyan]{graph.edge_count:,}[/cyan] edges\n")
    else:
        print(f"  graph: {graph.node_count} nodes  {graph.edge_count} edges\n")

    engine      = TraversalEngine()
    entry_nodes = engine.find_entry_nodes(incident, graph, None)

    if HAS_RICH:
        console.print(f"  Matched [bold cyan]{len(entry_nodes)}[/bold cyan]"
                      f" of {len(incident.frames)} frames to graph nodes:\n")
        for nid in entry_nodes:
            node = graph.get_node(nid)
            if node:
                console.print(
                    f"  [green]→[/green]  [bold]{node.name:<30}[/bold]"
                    f"  [dim]{os.path.basename(node.file_path)}[/dim]"
                )
    else:
        print(f"  entry nodes found: {len(entry_nodes)}")
        for nid in entry_nodes:
            node = graph.get_node(nid)
            if node:
                print(f"    → {node.name}  ({os.path.basename(node.file_path)})")

    _wait()

    # ── STEP 2: PHASE 3 — hop-by-hop traversal ────────────────────────────────
    _rule("Phase 3 · Bidirectional BFS Traversal")
    _pr("  Walking forward (callees) and backward (callers), scoring every node.\n"
        if not HAS_RICH else
        "  [dim]Walking forward (callees) and backward (callers), scoring every node.[/dim]\n")

    result  = engine.traverse(entry_nodes, graph, incident)
    by_hop  = defaultdict(list)
    for c in result.candidate_root_causes:
        by_hop[c.hops_from_entry].append(c)

    max_hop = max(by_hop.keys()) if by_hop else 0

    for hop in sorted(by_hop.keys()):
        candidates = by_hop[hop]
        label = "entry nodes  (in traceback)" if hop == 0 else "discovered via graph traversal"

        if HAS_RICH:
            console.print(
                f"  [bold]Hop {hop}[/bold]  [dim]{label}  ·  {len(candidates)} candidates[/dim]\n"
            )
            for c in candidates[:4]:
                console.print(
                    f"  [cyan]·[/cyan]  [bold]{c.node_name:<28}[/bold]"
                    f"  [dim]{os.path.basename(c.file_path)}[/dim]"
                )
            console.print()
        else:
            print(f"  Hop {hop}  —  {label}  ({len(candidates)} candidates)")
            for c in candidates[:4]:
                print(f"    · {c.node_name:<28}  {os.path.basename(c.file_path)}")
            print()

        if hop < max_hop:
            _wait(f"Press Enter to expand to hop {hop + 1}")

    if HAS_RICH:
        console.print(
            f"  [dim]Nodes visited: [cyan]{len(result.visited_nodes)}[/cyan]"
            f"   Hops completed: [cyan]{result.hops_completed}[/cyan][/dim]"
        )
    else:
        print(f"  nodes visited: {len(result.visited_nodes)}"
              f"   hops: {result.hops_completed}")

    _wait("Press Enter to verify candidates")

    # ── STEP 2: PHASE 4 — verification per candidate ──────────────────────────
    _rule("Phase 4 · Verify Each Candidate")
    _pr("  [dim]Running 3 checks per candidate — path exists, git evidence, keyword match.[/dim]\n"
        if HAS_RICH else
        "  Running 3 checks per candidate — path exists, git evidence, keyword match.\n")

    verifier = Verifier()
    verified = verifier.verify_candidates(
        result.candidate_root_causes, entry_nodes, graph, incident, top_n=5
    )

    for vr in verified:
        c = vr.candidate
        if HAS_RICH:
            p_icon = "[green]✓[/green]" if vr.path_exists   else "[red]✗[/red]"
            g_icon = "[green]✓[/green]" if vr.git_confirms  else "[red]✗[/red]"
            k_icon = "[green]✓[/green]" if vr.keyword_match else "[red]✗[/red]"
            if vr.is_valid:
                conf_color = "green" if vr.confidence == "high" else "yellow"
                verdict = f"[{conf_color}]VALID · {vr.confidence.upper()}[/{conf_color}]"
            else:
                verdict = "[red]eliminated[/red]"
            console.print(
                f"  [bold]{c.node_name:<26}[/bold] [dim]{os.path.basename(c.file_path)}[/dim]\n"
                f"    {p_icon} path_exists  "
                f"  {g_icon} git_confirms  "
                f"  {k_icon} keyword_match  "
                f"  → {verdict}\n"
            )
        else:
            p = "✓" if vr.path_exists   else "✗"
            g = "✓" if vr.git_confirms  else "✗"
            k = "✓" if vr.keyword_match else "✗"
            verdict = f"VALID · {vr.confidence.upper()}" if vr.is_valid else "eliminated"
            print(f"  {c.node_name:<26} {os.path.basename(c.file_path)}")
            print(f"    {p} path_exists   {g} git_confirms   {k} keyword_match  → {verdict}\n")
        time.sleep(0.4)

    best = next((v for v in verified if v.is_valid), None) or verified[0]
    _wait("Press Enter for the result")

    # ── REVEAL ────────────────────────────────────────────────────────────────
    _pr()

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
    _rule("End of demo")
    _pr()
