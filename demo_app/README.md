# Incident Diagnostics — Demos

Two ways to show off the knowledge-graph root-cause engine. Both run against
the toy `demo-codebase/` and its pre-built graph (`output/demo-codebase_graph.pkl`).

The scenario in one line: a request crashes with
`AttributeError: 'NoneType' object has no attribute 'total'` in
`payment.py::charge`, but the **real** bug is `config.py::get_payment_timeout()`
returning `0` instead of `30` — **3 hops upstream and nowhere in the stacktrace.**

```
handle_request → place_order → charge → get_cart → load_timeout → get_payment_timeout  ← bug
                                  ↑ crash surfaces here          ↑ root cause lives here
```

---

## Demo 1 — No-LLM root-cause UI (Flask)

A web page: paste a stacktrace, get the root cause. **No LLM anywhere** —
pure graph traversal + verification (`StackTraceParser → TraversalEngine →
Verifier`), typically ~1 ms.

```bash
pip install flask
python3 demo_app/server.py
# open http://127.0.0.1:5000
```

The page shows: the parsed incident, the headline root cause (with confidence,
hops-from-crash, the three verification checks, git evidence), the full ranked
candidate list, pipeline timings, and the traversal path.

> The headline is the **highest-confidence verified** candidate. The crash-site
> node may score marginally higher, but only the upstream cause clears all
> three checks (path · git · keyword) — so that is what gets surfaced.

**API** (for wiring elsewhere):
```bash
curl -X POST http://127.0.0.1:5000/api/diagnose \
  -H 'Content-Type: application/json' \
  -d '{"trace": "Traceback ...\nAttributeError: ..."}'
```

---

## Demo 2 — Claude Haiku, with vs. without our tool

Same model (Claude Haiku, via the `claude` CLI), same stacktrace. The only
variable is whether the graph engine's diagnosis is in the prompt.

```bash
python3 demo_app/compare_haiku.py            # live: runs Haiku twice + the tool
python3 demo_app/compare_haiku.py --tool-only # just the deterministic engine
```

- **Haiku WITHOUT tool** gets the stacktrace + the source of the files that
  appear in it (`app.py`, `order.py`, `payment.py`). It reaches the *proximate*
  cause (cart is `None` in `charge`) but can't reach the real bug — that code
  isn't in the trace, so it never sees it.
- **Haiku WITH tool** gets the same context **plus** the engine's diagnosis and
  the source of the off-trace files the engine flagged (`session.py`,
  `config.py`). It then correctly pins `get_payment_timeout` and gives the fix.

Both Haiku runs are isolated in an empty temp dir so neither can wander the
repo — the comparison is purely "did the tool's output help?".

Typical result:

| | found the real root cause? | cost |
|---|---|---|
| Haiku alone | ❌ blames the crash site | ~8 s, tokens |
| Haiku + our tool | ✅ `config.py::get_payment_timeout`, with the fix | ~6 s, tokens |
| Our tool alone (no LLM) | ✅ | ~1 ms, 0 tokens |

> Requires the `claude` CLI on PATH with Haiku access. The `--tool-only` path
> needs no LLM at all.

---

## Files

| File | Purpose |
|---|---|
| `diagnose_service.py` | Shared, LLM-free `diagnose(trace) → dict`. Loads + git-seeds the graph once. |
| `sample_traces.py` | The faithful primary trace + presets. |
| `server.py` + `templates/index.html` | Demo 1 — Flask UI. |
| `compare_haiku.py` | Demo 2 — Haiku with/without the tool. |
