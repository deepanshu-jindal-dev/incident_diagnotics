import pickle
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from diagnosis.stack_trace_parser import StackTraceParser
from diagnosis.traversal_engine import TraversalEngine
from diagnosis.verifier import Verifier
from semantic.tfidf_enricher import TFIDFEnricher

# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

W  = 80
C1 = 32
C2 = 12
C3 = 22

def banner(title: str) -> None:
    print("\n" + "═" * W)
    print(f"  {title}")
    print("═" * W)

def section(title: str) -> None:
    print("\n" + "─" * W)
    print(f"  {title}")
    print("─" * W)


# ─────────────────────────────────────────────────────────────────────────────
# Load graph + enricher (once, shared across all test cases)
# ─────────────────────────────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "output")
GRAPH_PATH = os.path.join(OUTPUT_DIR, "merged_graph.pkl")
TFIDF_PATH = os.path.join(OUTPUT_DIR, "merged_tfidf.json")

banner("INCIDENT DIAGNOSTICS ENGINE — test_traversal.py")

with open(GRAPH_PATH, "rb") as fh:
    graph = pickle.load(fh)

print(f"\n  Graph loaded")
print(f"    nodes : {graph.node_count}")
print(f"    edges : {graph.edge_count}")

if os.path.exists(TFIDF_PATH):
    enricher = TFIDFEnricher.load(TFIDF_PATH)
    print(f"\n  TF-IDF index loaded from {os.path.basename(TFIDF_PATH)}")
    print(f"    indexed nodes : {len(enricher._node_vectors)}")
else:
    print(f"\n  TF-IDF index not found — building...")
    enricher = TFIDFEnricher()
    enricher.enrich(graph)
    enricher.save(TFIDF_PATH)
    print(f"    indexed nodes : {len(enricher._node_vectors)}")
    print(f"    saved to      : {os.path.basename(TFIDF_PATH)}")


# ─────────────────────────────────────────────────────────────────────────────
# Test cases
# ─────────────────────────────────────────────────────────────────────────────

TEST_CASES = [

    ("TC1 — 404 Not Found  (flask → werkzeug, hop 1)", """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1596, in wsgi_app
    response = self.full_dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 982, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File "/output/clones/flask/src/flask/app.py", line 881, in handle_user_exception
    reraise(exc_type, exc_value, tb)
  File "/output/clones/werkzeug/src/werkzeug/routing/map.py", line 691, in match
    raise NotFound() from None
werkzeug.exceptions.NotFound: 404 Not Found: The requested URL was not found on the server.
"""),

    ("TC2 — MethodNotAllowed  (flask → werkzeug, hop 1)", """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1596, in wsgi_app
    response = self.full_dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 846, in handle_http_exception
    return handler(exc)
  File "/output/clones/werkzeug/src/werkzeug/routing/map.py", line 686, in match
    raise MethodNotAllowed(valid_methods=list(e.have_match_for)) from None
werkzeug.exceptions.MethodNotAllowed: 405 Method Not Allowed: The method is not allowed for the requested URL.
"""),

    ("TC3 — TemplateNotFound  (flask → jinja → loaders, hop 3)", """
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
  File "/output/clones/jinja/src/jinja2/environment.py", line 974, in _load_template
    template = self.loader.load(self, name, self.make_globals(globals))
  File "/output/clones/jinja/src/jinja2/loaders.py", line 215, in get_source
    raise TemplateNotFound(template)
jinja2.exceptions.TemplateNotFound: dashboard.html
"""),

    ("TC4 — UndefinedError  (flask → jinja → runtime, hop 3)", """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 982, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File "/output/clones/flask/src/flask/templating.py", line 148, in render_template
    return _render(ctx, t, ctx_dict)
  File "/output/clones/flask/src/flask/templating.py", line 135, in _render
    rv = template.render(context)
  File "/output/clones/jinja/src/jinja2/environment.py", line 1290, in render
    self.environment.handle_exception()
  File "/output/clones/jinja/src/jinja2/environment.py", line 953, in handle_exception
    raise rewrite_traceback_stack(source=source)
  File "/output/clones/jinja/src/jinja2/runtime.py", line 922, in _fail_with_undefined_error
    raise UndefinedError(hint)
jinja2.exceptions.UndefinedError: 'order' is undefined
"""),

    ("TC5 — AppContext teardown  (flask only, hop 3)", """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1596, in wsgi_app
    response = self.full_dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 1037, in finalize_request
    response = self.process_response(ctx, response)
  File "/output/clones/flask/src/flask/app.py", line 1410, in process_response
    self.do_teardown_request(ctx, exc)
  File "/output/clones/flask/src/flask/app.py", line 1436, in do_teardown_request
    func(exc)
  File "/output/clones/flask/src/flask/ctx.py", line 464, in pop
    self.app.do_teardown_appcontext(exc)
  File "/output/clones/flask/src/flask/app.py", line 1469, in do_teardown_appcontext
    func(exc)
RuntimeError: Working outside of application context.
"""),

    ("TC6 — Natural language query  (no stack trace, TF-IDF path)", """
Template rendering is broken. When users request pages that require Jinja2 templates,
the template loader cannot find the template file and raises a TemplateNotFound error.
The issue seems to be in how the Jinja2 environment loads templates from the file system.
"""),

]


# ─────────────────────────────────────────────────────────────────────────────
# Test runner
# ─────────────────────────────────────────────────────────────────────────────

def run_test(name: str, raw_trace: str) -> dict:
    case_name = name  # `name` is reused as a loop variable below; keep the original.
    banner(name)

    parser_obj = StackTraceParser()
    incident   = parser_obj.parse(raw_trace)

    # ── Phase 1: parsing ──────────────────────────────────────────────
    section("PHASE 1 — STACK TRACE PARSING")
    input_mode = "stack trace" if incident.frames else "natural language"
    print(f"\n  input mode    : {input_mode}")
    print(f"  error_type    : {incident.error_type or '(none)'}")
    print(f"  error_message : {incident.error_message or '(none)'}")
    print(f"  language      : {incident.language}")
    print(f"  keywords      : {incident.keywords}")
    if incident.frames:
        print(f"\n  {'FILE':<40}  {'LINE':>5}  FUNCTION")
        print(f"  {'─'*40}  {'─'*5}  {'─'*20}")
        for frame in incident.frames:
            fname = (frame.file_path or "?")[-40:]
            print(f"  {fname:<40}  {frame.line_number:>5}  {frame.function_name or '?'}")
    else:
        print(f"\n  (no frames — TF-IDF semantic search will be used for entry nodes)")

    # ── Phase 2: entry nodes ──────────────────────────────────────────
    discovery_method = "exact frame match" if incident.frames else "TF-IDF semantic search"
    section(f"PHASE 2 — ENTRY NODE DISCOVERY  [{discovery_method}]")
    engine      = TraversalEngine()
    entry_nodes = engine.find_entry_nodes(incident, graph, enricher=enricher)
    print(f"\n  Found {len(entry_nodes)} entry node(s)\n")
    print(f"  {'NAME':<{C1}}  {'TYPE':<{C2}}  FILE")
    print(f"  {'─'*C1}  {'─'*C2}  {'─'*C3}")
    for nid in entry_nodes:
        node = graph.get_node(nid)
        if node is None:
            print(f"  {'<missing>':<{C1}}  {'?':<{C2}}  {nid}")
            continue
        fname = os.path.basename(node.file_path or "?")
        print(f"  {(node.name or '?'):<{C1}}  {(node.type or '?'):<{C2}}  {fname}")

    # ── Phase 3 ───────────────────────────────────────────────────────
    section("PHASE 3 — TRAVERSAL RESULT SUMMARY")
    result = engine.traverse(entry_nodes, graph, incident)
    print(f"\n  hops completed : {result.hops_completed}")
    print(f"  nodes visited  : {len(result.visited_nodes)}")

    if result.errors:
        print(f"\n  Errors ({len(result.errors)}):")
        for e in result.errors:
            print(f"    ! {e}")

    print(f"\n  Top 5 root-cause candidates\n")
    print(f"  {'SCORE':>7}  {'HOPS':>4}  {'LINE':>5}  {'NAME':<{C1}}  {'TYPE':<{C2}}  FILE")
    print(f"  {'─'*7}  {'─'*4}  {'─'*5}  {'─'*C1}  {'─'*C2}  {'─'*C3}")
    for c in result.candidate_root_causes[:5]:
        fname = os.path.basename(c.file_path) if c.file_path else "?"
        nname = (c.node_name or "?")[:C1]
        ntype = (c.node_type or "?")[:C2]
        lineno = str(c.line_number) if c.line_number else "?"
        print(f"  {c.score:>7.4f}  {c.hops_from_entry:>4}  {lineno:>5}  {nname:<{C1}}  {ntype:<{C2}}  {fname}")
        for reason in c.reasons:
            print(f"  {' '*7}  {' '*4}  {' '*5}  └─ {reason}")

    # ── Phase 4: verification ─────────────────────────────────────────
    section("PHASE 4 — VERIFICATION")
    verifier = Verifier()
    verified = verifier.verify_candidates(
        result.candidate_root_causes,
        entry_nodes,
        graph,
        incident,
        top_n=5,
    )

    print(f"\n  {len(verified)} candidate(s) verified\n")
    print(f"  {'#':<3}  {'NAME':<{C1}}  {'LINE':>5}  {'CONF':<8}  {'VALID':<6}  {'PASSED':<30}  FILE")
    print(f"  {'─'*3}  {'─'*C1}  {'─'*5}  {'─'*8}  {'─'*6}  {'─'*30}  {'─'*C3}")
    for i, vr in enumerate(verified):
        name   = (vr.candidate.node_name if vr.candidate else "?")[:C1]
        fpath  = os.path.basename(vr.candidate.file_path or "?") if vr.candidate else "?"
        lineno = str(vr.candidate.line_number) if (vr.candidate and vr.candidate.line_number) else "?"
        passed = ", ".join(vr.checks_passed) or "—"
        valid  = "yes" if vr.is_valid else "no"
        print(f"  {i+1:<3}  {name:<{C1}}  {lineno:>5}  {vr.confidence:<8}  {valid:<6}  {passed:<30}  {fpath}")

    print(f"\n  Detail\n")
    for i, vr in enumerate(verified):
        name   = vr.candidate.node_name if vr.candidate else "?"
        fpath  = os.path.basename(vr.candidate.file_path or "?") if vr.candidate else "?"
        lineno = vr.candidate.line_number if (vr.candidate and vr.candidate.line_number) else "?"
        score  = vr.candidate.score if vr.candidate else 0.0
        print(f"  #{i+1}  {name}  ({fpath}:{lineno})")
        print(f"       score        : {score:.4f}")
        print(f"       confidence   : {vr.confidence}")
        print(f"       is_valid     : {vr.is_valid}")
        print(f"       path_exists  : {vr.path_exists}")
        print(f"       git_confirms : {vr.git_confirms}")
        print(f"       keyword_match: {vr.keyword_match}")
        print(f"       passed       : {vr.checks_passed}")
        print(f"       failed       : {vr.checks_failed}")
        print()

    # ── Best candidate ────────────────────────────────────────────────
    section("BEST CANDIDATE FOR LLM")
    best = verified[0] if verified else None
    if best and best.is_valid:
        lineno = best.candidate.line_number if best.candidate.line_number else "?"
        print(f"\n  {best.candidate.node_name}  (line {lineno})  —  confidence: {best.confidence}\n")
        print(f"  explanation_context:")
        print(f"  {'─'*(W-4)}")
        for line in best.explanation_context.split(". "):
            if line.strip():
                print(f"    {line.strip()}.")
    else:
        print("\n  No valid root cause found.")

    # Hand the outcome back to the top-level runner for the final summary.
    if best and best.candidate:
        cand = best.candidate
        return {
            "name": case_name,
            "valid": best.is_valid,
            "node": cand.node_name or "?",
            "file": os.path.basename(cand.file_path or "") or "?",
            "line": cand.line_number if cand.line_number else "?",
        }
    return {
        "name": case_name, "valid": False, "node": "—",
        "file": "—", "line": "—",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Run all test cases
# ─────────────────────────────────────────────────────────────────────────────

SUMMARY = []

for tc_name, tc_trace in TEST_CASES:
    SUMMARY.append(run_test(tc_name, tc_trace))

banner("ALL TESTS COMPLETE — RESULTS")
print()
print(f"  {'#':<3} {'CASE':<26} {'VALID':<6} {'ROOT CAUSE':<22} {'FILE':<16} {'LINE':>5}")
print(f"  {'─'*3} {'─'*26} {'─'*6} {'─'*22} {'─'*16} {'─'*5}")
for i, r in enumerate(SUMMARY, 1):
    # Drop the parenthetical hint from the case name to keep the row compact.
    short_name = r["name"].split("  (")[0][:26]
    valid = "yes" if r["valid"] else "no"
    print(f"  {i:<3} {short_name:<26} {valid:<6} {r['node'][:22]:<22} "
          f"{r['file'][:16]:<16} {str(r['line']):>5}")
print()

valid_count = sum(1 for r in SUMMARY if r["valid"])
print(f"  {valid_count}/{len(SUMMARY)} cases produced a valid root cause.")
print("─" * W)
