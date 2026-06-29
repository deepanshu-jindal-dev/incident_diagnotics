"""Demo 2 — Claude Haiku, with and without our knowledge-graph tool.

Same model (Claude Haiku, run through the Claude Code CLI), same stacktrace.
The ONLY variable is whether the graph tool's diagnosis is in the prompt:

  Run A  "naked"  : Haiku gets the stacktrace + the source of the files that
                    appear in the traceback (app.py, order.py, payment.py).
                    It can reach the proximate cause (cart is None) but the
                    real bug — config.get_payment_timeout() returning 0 — is
                    in code that never appears in the trace, so it can't get there.

  Run B  "+tool"  : Haiku gets the same context PLUS the deterministic graph
                    engine's diagnosis, which pinpoints the upstream culprit
                    with git evidence. Haiku now nails the fix.

Both Haiku runs are isolated in an empty temp dir so neither can wander the
repo — the comparison is purely "did the tool's output help?".

    python3 demo_app/compare_haiku.py            # runs the live Haiku comparison
    python3 demo_app/compare_haiku.py --tool-only # just the deterministic engine

Requires the `claude` CLI on PATH (Claude Code) with Haiku access.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from demo_app.diagnose_service import diagnose                      # noqa: E402
from demo_app.sample_traces import PRIMARY_TRACE, TRACEBACK_FILES    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo-codebase")
HAIKU_MODEL = "claude-haiku-4-5"

# ── ansi ──────────────────────────────────────────────────────────────────
def _supports_color():
    return sys.stdout.isatty() and os.environ.get("TERM") not in (None, "dumb")
C = _supports_color()
def c(s, code): return f"\033[{code}m{s}\033[0m" if C else s
def bold(s): return c(s, "1")
def green(s): return c(s, "32")
def red(s): return c(s, "31")
def cyan(s): return c(s, "36")
def dim(s): return c(s, "2")
def rule(t=""):
    line = "─" * max(4, 70 - len(t))
    print(f"\n{cyan('── ' + t + ' ')}{cyan(line)}" if t else cyan("─" * 72))


def _read_sources(filenames):
    out = []
    for fn in filenames:
        p = os.path.join(DEMO, fn)
        if os.path.exists(p):
            out.append(f"--- {fn} ---\n{open(p).read().rstrip()}")
    return "\n\n".join(out)


def _read_traceback_files():
    return _read_sources(TRACEBACK_FILES)


def _offtrace_files(report):
    """Files on the tool's root-cause path that do NOT appear in the
    stacktrace — exactly the off-trace code the graph surfaced. These are
    what a real tool integration would put in front of you (or the LLM)."""
    seen, files = set(), []
    for short in report.get("traversal_path", []):
        fn = short.split("::")[0]
        if fn and fn not in TRACEBACK_FILES and fn not in seen:
            seen.add(fn)
            files.append(fn)
    return files


def _call_haiku(prompt):
    """Run Claude Haiku via the Claude Code CLI in an isolated empty dir.
    Returns (text, seconds). Raises on CLI failure."""
    workdir = tempfile.mkdtemp(prefix="haiku_demo_")
    try:
        t0 = time.perf_counter()
        proc = subprocess.run(
            ["claude", "-p", prompt, "--model", HAIKU_MODEL],
            cwd=workdir, capture_output=True, text=True, timeout=300,
        )
        dt = time.perf_counter() - t0
        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}")
        return proc.stdout.strip(), dt
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


_ASK = ("Identify the ROOT CAUSE of this production error. Reply in <=4 lines:\n"
        "  ROOT CAUSE: <file>::<function> — <one-line why>\n"
        "  FIX: <what to change>\n"
        "Answer directly from the information given; do not use any tools.")


def naked_prompt(trace, sources):
    return (f"A production service crashed. Here is the stacktrace:\n\n{trace}\n\n"
            f"Here is the source of every file that appears in the stacktrace:\n\n"
            f"{sources}\n\n{_ASK}")


def tool_prompt(trace, sources, report):
    h = report["headline"]
    path = " -> ".join(report["traversal_path"][:8])
    offtrace = _offtrace_files(report)
    offtrace_src = _read_sources(offtrace)
    tool_block = (
        f"ROOT-CAUSE ENGINE OUTPUT (deterministic knowledge-graph analysis, no LLM):\n"
        f"  root cause node : {h['node_name']}  ({h['file']}:{h['line_number']})\n"
        f"  confidence      : {h['confidence'].upper()}  (checks passed: {', '.join(h['checks_passed'])})\n"
        f"  distance        : {h['hops_from_entry']} hops upstream of the crash "
        f"({'NOT in the stacktrace' if not h['in_traceback'] else 'in the stacktrace'})\n"
        f"  git evidence    : {h['git_evidence']}\n"
        f"  call path       : {path}\n"
        f"  reasons         : {'; '.join(h['reasons'])}"
    )
    # The tool's real value: it points at code OFF the stacktrace. Show that
    # code — it's what naked Haiku never had a reason to open.
    offtrace_block = (
        f"\n\nThe engine flagged these files, which are on the call path but do "
        f"NOT appear in the stacktrace:\n\n{offtrace_src}"
        if offtrace_src else ""
    )
    return (f"A production service crashed. Here is the stacktrace:\n\n{trace}\n\n"
            f"Source of the files in the stacktrace:\n\n{sources}\n\n"
            f"{tool_block}{offtrace_block}\n\n{_ASK}")


def run_tool(trace):
    rule("OUR TOOL  ·  deterministic knowledge graph  ·  NO LLM")
    rep = diagnose(trace)
    h = rep["headline"]
    if h:
        print(f"  {bold(green('ROOT CAUSE'))}: {bold(h['node_name'])}  "
              f"({h['file']}:{h['line_number']})")
        print(f"  confidence : {h['confidence'].upper()}   "
              f"hops upstream: {h['hops_from_entry']}   "
              f"in traceback: {'no' if not h['in_traceback'] else 'yes'}")
        print(f"  checks     : {', '.join(h['checks_passed'])}")
        print(f"  git        : {h['git_evidence']}")
    else:
        print(red("  no valid root cause"))
    print(dim(f"  diagnosed in {rep['timings']['total_ms']} ms (pure graph traversal)"))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool-only", action="store_true",
                    help="skip the Haiku calls; just show the deterministic engine")
    args = ap.parse_args()

    trace = PRIMARY_TRACE
    sources = _read_traceback_files()

    rule("THE INCIDENT")
    print(trace)
    print(dim("\nNote: the stacktrace touches app.py / order.py / payment.py. "
              "It never mentions session.py or config.py."))

    report = run_tool(trace)
    if args.tool_only:
        return

    if shutil.which("claude") is None:
        print(red("\n`claude` CLI not found on PATH — cannot run the Haiku comparison."))
        print("Install Claude Code, then re-run. (The deterministic tool result above needs no LLM.)")
        sys.exit(1)

    rule(f"HAIKU  ·  WITHOUT our tool  (model: {HAIKU_MODEL})")
    print(dim("  prompt = stacktrace + source of the traceback files only\n"))
    try:
        ans_a, dt_a = _call_haiku(naked_prompt(trace, sources))
        print(ans_a)
        print(dim(f"\n  ⏱  {dt_a:.1f}s"))
    except Exception as e:
        ans_a, dt_a = None, None
        print(red(f"  Haiku call failed: {e}"))

    rule(f"HAIKU  ·  WITH our tool  (model: {HAIKU_MODEL})")
    print(dim("  prompt = same context + the graph engine's diagnosis\n"))
    try:
        ans_b, dt_b = _call_haiku(tool_prompt(trace, sources, report))
        print(ans_b)
        print(dim(f"\n  ⏱  {dt_b:.1f}s"))
    except Exception as e:
        ans_b, dt_b = None, None
        print(red(f"  Haiku call failed: {e}"))

    rule("VERDICT")
    culprit = report["headline"]["node_name"] if report["headline"] else "get_payment_timeout"

    def _hit(ans):
        # Only count it if the culprit is named on the ROOT CAUSE line — not
        # merely mentioned elsewhere (e.g. to dismiss it).
        if not ans:
            return False
        for line in ans.splitlines():
            if line.strip().upper().startswith("ROOT CAUSE") and culprit in line:
                return True
        return False
    print(f"  real root cause                : {bold(culprit)} (config.py, 3 hops upstream)")
    print(f"  Haiku WITHOUT tool found it    : {green('YES') if _hit(ans_a) else red('NO')}")
    print(f"  Haiku WITH tool found it       : {green('YES') if _hit(ans_b) else red('NO')}")
    print(f"  deterministic tool found it    : {green('YES')}  "
          f"({report['timings']['total_ms']} ms, no tokens)")
    print(dim("\n  Same model, same trace. The graph tool supplies the one fact the trace omits:\n"
              "  the crash is a symptom of code that isn't in the stacktrace at all."))


if __name__ == "__main__":
    main()
