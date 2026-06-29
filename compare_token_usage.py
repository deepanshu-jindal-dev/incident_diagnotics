"""Token Usage Showdown — Graph Engine vs LLM with full codebase access.

Three approaches, same goal: find the root cause of a production crash.

  Mode A  Naked LLM      — trace only, no codebase access
  Mode B  LLM + Codebase — trace + every source file dumped into the prompt
  Mode C  Graph Engine   — zero LLM tokens, deterministic graph traversal

Shows exactly how many tokens each approach costs and whether it finds
the correct root cause.

    python3 compare_token_usage.py
    python3 compare_token_usage.py --no-llm   # skip LLM calls, show token math only
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, "src")
DEMO = os.path.join(ROOT, "demo-codebase")
for _p in (ROOT, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from demo_app.diagnose_service import diagnose           # noqa: E402
from demo_app.sample_traces import PRESETS               # noqa: E402

# ── ANSI helpers ──────────────────────────────────────────────────────────────
def _tty(): return sys.stdout.isatty()
def c(s, *codes): return (f"\033[{';'.join(str(x) for x in codes)}m{s}\033[0m") if _tty() else s
def bold(s):   return c(s, 1)
def dim(s):    return c(s, 2)
def green(s):  return c(s, 32)
def red(s):    return c(s, 31)
def yellow(s): return c(s, 33)
def cyan(s):   return c(s, 36)
def blue(s):   return c(s, 34)
def white(s):  return c(s, 97)
def bg_green(s): return c(s, 42, 30, 1)
def bg_red(s):   return c(s, 41, 97, 1)
def bg_blue(s):  return c(s, 44, 30, 1)

W = 72

def rule(title="", ch="─"):
    if title:
        pad = ch * max(2, (W - len(title) - 4) // 2)
        print(f"\n{cyan(pad)}  {bold(white(title))}  {cyan(pad)}")
    else:
        print(cyan(ch * W))

def banner(title, sub=""):
    print("\n" + cyan("╔" + "═"*(W-2) + "╗"))
    print(cyan("║") + f"  {bold(white(title)):<{W-4}}  " + cyan("║"))
    if sub:
        print(cyan("║") + f"  {dim(sub):<{W-4}}  " + cyan("║"))
    print(cyan("╚" + "═"*(W-2) + "╝"))

def section(label, color_fn=cyan):
    print(f"\n  {color_fn('▶')} {bold(label)}")
    print(f"  {dim('─'*60)}")

def kv(key, val, key_w=28):
    print(f"  {dim(key.ljust(key_w))} {val}")


# ── Token counting (no external deps) ────────────────────────────────────────
def estimate_tokens(text: str) -> int:
    """~4 chars per token for English/code — conservative estimate."""
    return max(1, len(text) // 4)

def format_tokens(n: int) -> str:
    if n == 0:
        return bold(green("0"))
    if n < 1_000:
        return yellow(f"{n:,}")
    if n < 10_000:
        return yellow(f"{n:,}")
    if n < 100_000:
        return red(f"{n:,}")
    return bold(red(f"{n:,}"))


# ── Spinner ───────────────────────────────────────────────────────────────────
class Spinner:
    _FRAMES = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
    def __init__(self, msg):
        self._msg = msg
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
    def _run(self):
        i = 0
        while not self._stop:
            frame = cyan(self._FRAMES[i % len(self._FRAMES)])
            print(f"\r  {frame}  {self._msg}", end="", flush=True)
            time.sleep(0.08)
            i += 1
    def __enter__(self):
        if _tty(): self._t.start()
        else: print(f"  … {self._msg}")
        return self
    def __exit__(self, *_):
        self._stop = True
        if _tty(): print("\r" + " "*60 + "\r", end="", flush=True)


# ── LLM call ─────────────────────────────────────────────────────────────────
HAIKU = "claude-haiku-4-5-20251001"
_ASK = (
    "Identify the ROOT CAUSE of this production error. Reply in ≤4 lines:\n"
    "  ROOT CAUSE: <file>::<function> — <one-line why>\n"
    "  FIX: <what to change>\n"
    "Answer directly from the information given. Do not use any tools."
)

def call_haiku(prompt: str) -> tuple:
    """Returns (answer, elapsed_seconds). Raises on failure."""
    wd = tempfile.mkdtemp(prefix="tok_demo_")
    try:
        t0 = time.perf_counter()
        r = subprocess.run(
            ["claude", "-p", prompt, "--model", HAIKU],
            cwd=wd, capture_output=True, text=True, timeout=180,
        )
        dt = time.perf_counter() - t0
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[:200])
        return r.stdout.strip(), dt
    finally:
        import shutil as _sh; _sh.rmtree(wd, ignore_errors=True)


# ── Codebase loader ───────────────────────────────────────────────────────────
def load_codebase_files(directory: str, exts=(".py",), max_files=200) -> list:
    """Walk directory, return list of (relpath, content) tuples."""
    files = []
    skip = {"__pycache__", ".git", "venv", ".venv", "node_modules"}
    for root, dirs, fnames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in skip]
        for fn in fnames:
            if not any(fn.endswith(e) for e in exts): continue
            fp = os.path.join(root, fn)
            try:
                text = open(fp).read()
                rel  = os.path.relpath(fp, directory)
                files.append((rel, text))
            except Exception:
                pass
            if len(files) >= max_files:
                return files
    return files

def files_to_prompt_block(files: list) -> str:
    parts = []
    for rel, text in files:
        parts.append(f"=== {rel} ===\n{text.rstrip()}")
    return "\n\n".join(parts)


# ── Repo scale table ──────────────────────────────────────────────────────────
REPO_SCALE = [
    ("Demo Codebase",  DEMO,                                                      "9 files"),
    ("Flask",          os.path.join(ROOT, "output/clones/flask/src"),             "~60 files"),
    ("TensorFlow ops", os.path.join(ROOT, "output/clones/tensorflow/tensorflow/python/ops"), "~400 files"),
]


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="Skip LLM calls, show token math only")
    ap.add_argument("--trace", default="trace_1", help="Preset key (trace_1…trace_c)")
    args = ap.parse_args()

    trace_key = args.trace if args.trace in PRESETS else "trace_1"
    preset    = PRESETS[trace_key]
    trace     = preset["trace"]

    banner(
        "Token Usage Showdown",
        "Graph Engine vs LLM — same goal, very different cost"
    )

    # ── Load codebase ─────────────────────────────────────────────────────────
    rule("CODEBASE")
    all_files   = load_codebase_files(DEMO)
    codebase_str = files_to_prompt_block(all_files)
    file_names  = [r for r, _ in all_files]

    kv("Directory",       DEMO)
    kv("Files loaded",    str(len(all_files)))
    kv("Total chars",     f"{len(codebase_str):,}")
    kv("Estimated tokens",format_tokens(estimate_tokens(codebase_str)))

    # ── Build prompts ─────────────────────────────────────────────────────────
    rule("PROMPTS")

    prompt_naked    = f"A production service crashed.\n\nStacktrace:\n{trace}\n\n{_ASK}"
    prompt_codebase = (f"A production service crashed.\n\nStacktrace:\n{trace}\n\n"
                       f"Here is the COMPLETE source code of the service:\n\n{codebase_str}\n\n{_ASK}")

    tok_naked    = estimate_tokens(prompt_naked)
    tok_codebase = estimate_tokens(prompt_codebase)

    kv("Mode A — trace only",         f"{format_tokens(tok_naked)} tokens")
    kv("Mode B — trace + codebase",   f"{format_tokens(tok_codebase)} tokens")
    kv("Mode C — graph engine",       f"{bold(green('0'))} LLM tokens")

    # ── Repo scale projection ─────────────────────────────────────────────────
    rule("AT SCALE — what 'dump the codebase' costs")
    print(f"\n  {'Codebase':<22} {'Files':<12} {'Est. tokens':<16} {'At $3/M tok'}")
    print(f"  {dim('─'*22)} {dim('─'*12)} {dim('─'*16)} {dim('─'*14)}")
    for name, path, note in REPO_SCALE:
        if os.path.isdir(path):
            fs = load_codebase_files(path, max_files=500)
            total_chars = sum(len(t) for _, t in fs)
            est = max(1, total_chars // 4)
            cost = est * 3 / 1_000_000
            print(f"  {name:<22} {f'{len(fs)} files ({note})':<12} {f'~{est:,}':<16} ${cost:.4f}")
        else:
            print(f"  {name:<22} {note:<12} {dim('(clone not found)')}")
    print(f"\n  {dim('Graph engine: always 0 tokens regardless of codebase size.')}")

    if args.no_llm:
        print(f"\n  {dim('--no-llm set — skipping LLM calls.')}")
        _print_summary(None, None, None, tok_naked, tok_codebase, "trace_1", preset)
        return

    if not shutil.which("claude"):
        print(f"\n  {yellow('⚠')}  claude CLI not found — skipping LLM calls.")
        _print_summary(None, None, None, tok_naked, tok_codebase, trace_key, preset)
        return

    # ── Mode A: Naked LLM ─────────────────────────────────────────────────────
    rule("MODE A — LLM without codebase access")
    kv("Prompt tokens",  format_tokens(tok_naked))
    print()
    ans_a = err_a = None
    t_a = 0.0
    with Spinner(f"Calling {HAIKU}…"):
        try:
            ans_a, t_a = call_haiku(prompt_naked)
        except Exception as e:
            err_a = str(e)

    if err_a:
        print(f"  {red('✗')} LLM call failed: {err_a}")
    else:
        print(f"  {cyan('Answer')} ({t_a:.1f}s):\n")
        for line in ans_a.splitlines():
            print(f"    {line}")

    # ── Mode B: LLM + full codebase ───────────────────────────────────────────
    rule("MODE B — LLM with full codebase dumped into prompt")
    kv("Prompt tokens",   format_tokens(tok_codebase))
    kv("Files in prompt", f"{len(all_files)}  ({', '.join(file_names[:4])}{'…' if len(file_names)>4 else ''})")
    print()
    ans_b = err_b = None
    t_b = 0.0
    with Spinner(f"Calling {HAIKU} with {tok_codebase:,} token prompt…"):
        try:
            ans_b, t_b = call_haiku(prompt_codebase)
        except Exception as e:
            err_b = str(e)

    if err_b:
        print(f"  {red('✗')} LLM call failed: {err_b}")
    else:
        print(f"  {cyan('Answer')} ({t_b:.1f}s):\n")
        for line in ans_b.splitlines():
            print(f"    {line}")

    # ── Mode C: Graph Engine ──────────────────────────────────────────────────
    rule("MODE C — Graph Engine (zero LLM tokens)")
    t3 = time.perf_counter()
    report = diagnose(trace, graph_key="demo-codebase")
    t_c = (time.perf_counter() - t3) * 1000
    h = report.get("headline") or {}
    if h:
        print(f"  {green('✓')} {bold(h['node_name'])}  —  {h['file']}:{h['line_number']}")
        print(f"  {dim('confidence:')} {h['confidence'].upper()}   "
              f"{dim('hops:')} {h['hops_from_entry']}   "
              f"{dim('in trace:')} {'yes' if h['in_traceback'] else 'no'}")
        print(f"  {dim('git:')} {h.get('git_evidence','—')}")
    print(f"  {dim('diagnosed in')} {bold(green(f'{t_c:.1f} ms'))}")

    _print_summary(ans_a, ans_b, report, tok_naked, tok_codebase, trace_key, preset, t_a, t_b, t_c)


def _print_summary(ans_a, ans_b, report, tok_naked, tok_codebase,
                   trace_key, preset, t_a=0, t_b=0, t_c=0):
    h = (report or {}).get("headline") or {}
    root = h.get("node_name") or preset.get("seed_node") or "?"

    def found(ans):
        if not ans or not root: return False
        for line in ans.split('\n'):
            if 'ROOT CAUSE' in line.upper() and root in line:
                return True
        return False

    hit_a = found(ans_a)
    hit_b = found(ans_b)

    rule("RESULTS", ch="═")
    print()
    W2 = 68
    print(f"  {'Mode':<28} {'Tokens':>10} {'Found RC':>10} {'Time':>10}")
    print(f"  {dim('─'*28)} {dim('─'*10)} {dim('─'*10)} {dim('─'*10)}")

    def row(mode, tokens, hit, time_str, highlight=False):
        tok_str = format_tokens(tokens) if tokens else bold(green("0"))
        hit_str = (bg_green(" YES ") if hit else bg_red(" NO  ")) if hit is not None else dim("  —  ")
        line = f"  {mode:<28} {tok_str:>10} {hit_str:>10} {dim(time_str):>10}"
        print(line)

    row("A  Naked LLM (trace only)",    tok_naked,    hit_a, f"{t_a:.1f}s" if t_a else "—")
    row("B  LLM + full codebase",       tok_codebase, hit_b, f"{t_b:.1f}s" if t_b else "—")
    row("C  Graph Engine  ← OUR TOOL",  0,            True,  f"{t_c:.0f}ms" if t_c else "<100ms", True)

    print()
    mult = tok_codebase // max(1, tok_naked)
    print(f"  {dim('Token overhead of dumping codebase:')}  {yellow(f'{mult}×')} more tokens than trace-only")
    print(f"  {dim('Token overhead vs graph engine:    ')}  {red('∞')}  (engine uses 0 LLM tokens)")

    print()
    print(f"  {dim('Root cause the engine found:')}  {bold(green(root))}")
    if not hit_a and ans_a:
        print(f"  {dim('Naked LLM said:')}  {red(ans_a.splitlines()[0][:60])}")
    print()
    print(cyan("═" * W))
    print()


if __name__ == "__main__":
    main()
