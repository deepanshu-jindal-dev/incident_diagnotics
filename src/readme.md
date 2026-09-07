# Incident Diagnostics Engine

A code-aware root-cause analysis engine. It ingests a source repository into a language-agnostic **knowledge graph** (functions, classes, modules, and the CALLS/IMPORTS/EXTENDS/RAISES relationships between them), then takes a raw production incident — a stack trace or a plain-English description — and traces it *backward through the call graph* to surface and verify the most likely root cause, with git-history and keyword evidence attached.

No LLM calls, no `ast` module, no Tree-sitter, no third-party parsing or ML libraries. Tokenizing, parsing, graph traversal, and TF-IDF search are all implemented from scratch in Python.

```
Repository  ──ingest──▶  Knowledge Graph  ──diagnose──▶  Root-Cause Report
 (source code)           (nodes + edges)        ▲
                                                 │
                                        Stack trace / incident text
```

---

## Table of Contents

- [How it works](#how-it-works)
- [Project structure](#project-structure)
- [Module reference](#module-reference)
  - [`graph/` — the knowledge graph](#graph--the-knowledge-graph)
  - [`parser/` — from-scratch language parsers](#parser--from-scratch-language-parsers)
  - [`ingestion/` — repo → graph pipeline](#ingestion--repo--graph-pipeline)
  - [`resolution/` — entity resolution](#resolution--entity-resolution)
  - [`semantic/` — enrichment](#semantic--enrichment)
  - [`diagnosis/` — the diagnosis pipeline](#diagnosis--the-diagnosis-pipeline)
  - [`storage/`, `tools/`, `tests/`](#storage-tools-tests)
- [Usage](#usage)
- [Scoring & confidence model](#scoring--confidence-model)
- [Design principles](#design-principles)

---

## How it works

The engine runs in two independent stages:

**1. Ingestion (build-time).** `ingestion/pipeline.py` walks a repository, and for every source file: tokenizes it, parses it into an AST, walks that AST to emit `Node`s (functions, classes, modules, variables) and `Edge`s (CALLS, IMPORTS, EXTENDS, RAISES, etc.), then resolves placeholder edge targets (raw symbol names like `"charge"`) into real node ids. The result is serialized to a pickle + JSON knowledge graph. Optionally, `semantic/git_enricher.py` attaches recent commit history to each node, and `semantic/tfidf_enricher.py` builds a semantic search index over node descriptions.

**2. Diagnosis (query-time).** `diagnose.py` loads the pre-built graph, parses an incoming stack trace or free-text description into a `ParsedIncident`, and hands it to `IncidentEngine`, which runs four phases:

| Phase | Component | Job |
|---|---|---|
| 1. Parse | `StackTraceParser` | Raw text → error type, message, stack frames, keywords |
| 2. Entry nodes | `TraversalEngine.find_entry_nodes` | Locate where in the graph the crash happened (exact match for traces, TF-IDF for free text) |
| 3. Traverse | `TraversalEngine.traverse` | Backward BFS over CALLS/IMPORTS/EXTENDS edges to collect and score candidate root causes |
| 4. Verify | `Verifier.verify_candidates` | Independently confirm the top candidates and assign a confidence level |

The output is a `DiagnosisReport`: the root-cause node, its file/line, a confidence level, the reasons behind the score, and any git evidence — never a raised exception, even on malformed input or a missing graph entry.

---

## Project structure

```
src/
├── diagnose.py                  # CLI entry point
├── graph/                       # language-agnostic graph data model
│   ├── node.py
│   ├── edge.py
│   └── graph.py
├── parser/                      # from-scratch tokenizers/parsers/walkers
│   ├── base_tokenizer.py
│   ├── base_parser.py
│   ├── python/                  # full Python support
│   │   ├── tokenizer.py
│   │   ├── parser.py
│   │   ├── ast_nodes.py
│   │   └── walker.py
│   └── javascript/               # placeholder for future JS support
├── ingestion/                    # repo → graph pipeline
│   ├── pipeline.py
│   ├── file_processor.py
│   ├── language_strategy.py
│   └── pipeline_reports.py
├── resolution/                   # placeholder-edge → real-node resolution
│   ├── entity_resolver.py
│   └── builtins_catalog.py
├── semantic/                     # optional enrichment passes
│   ├── git_enricher.py
│   └── tfidf_enricher.py
├── diagnosis/                    # the diagnosis pipeline
│   ├── stack_trace_parser.py
│   ├── frame_parsers.py
│   ├── language_detector.py
│   ├── traversal_engine.py
│   ├── verifier.py
│   ├── incident_engine.py
│   ├── scoring_config.py
│   └── scoring_utils.py
├── storage/
│   └── verify_storage.py
├── tools/
│   └── visualize_graph.py
└── tests/
    ├── test_traversal.py
    └── full_pipeline_proof.py
```

---

## Module reference

### `graph/` — the knowledge graph

The core data model everything else builds on.

- **`node.py`** — `Node` dataclass: `id`, `name`, `type` (`function` | `class` | `module` | `variable` | `parameter`), `file_path`, `line_number`, `language`, `docstring`, `metadata`, `confidence`. Node ids are canonical strings built via `Node.make_id(file_path, class_name, function_name)`, e.g. `"order.py::OrderService::place_order"`.
- **`edge.py`** — `Edge` dataclass with a fixed relationship vocabulary: `CALLS`, `IMPORTS`, `EXTENDS`, `IMPLEMENTS`, `INSTANTIATES`, `DECORATES`, `CONTAINS`, `RAISES`, `CATCHES`. Edges can be unresolved (`is_resolved=False`) with a `target_id` that's just a raw symbol name, until `resolution/` fixes them up.
- **`graph.py`** — `Graph`: in-memory directed graph with adjacency lists for O(degree) lookups (`get_edges_from`, `get_edges_to`, `get_neighbors`), plus JSON and pickle serialization (`serialize_to_json` / `deserialize_from_json`).

### `parser/` — from-scratch language parsers

No `ast` module, no Tree-sitter — every layer is hand-written.

- **`base_tokenizer.py` / `base_parser.py`** — abstract base classes every language plugs into: a `BaseTokenizer` turns source text into a token stream; a `BaseParser` consumes tokens and yields a structured tree.
- **`python/`** — the full, working implementation: `tokenizer.py` (lexer), `parser.py` (recursive-descent parser into `ast_nodes.py` node types), `walker.py` (walks the parsed tree to emit `Node`/`Edge` records into the graph — function/class/import/call/raise/decorator detection, etc.).
- **`javascript/`** — currently a stub package, reserved for a future JS/TS strategy alongside `PythonStrategy`.

### `ingestion/` — repo → graph pipeline

- **`pipeline.py`** — `IngestionPipeline.run(repo_path)`: discovers source files (skipping `.git`, `venv`, `node_modules`, `dist`, etc. and anything over 1 MiB), processes each file, runs entity resolution, and writes the resulting graph to disk as pickle + JSON. Also supports `run_multi()` to merge several repositories into one graph. Failures are per-file and non-fatal — a bad file is logged and skipped, not fatal to the run. Can clone a Git URL directly.
- **`file_processor.py`** — `_FileProcessorBuilder`: a fluent chain (`read → tokenize → parse → walk`) where any failed step short-circuits the rest without needing guard clauses at each call site.
- **`language_strategy.py`** — Strategy pattern mapping file extensions to a language's tokenizer/parser/walker triplet (`LANGUAGE_REGISTRY`, `SUPPORTED_EXTENSIONS`). `PythonStrategy` is implemented; this is the extension point for new languages.
- **`pipeline_reports.py`** — `PipelineReport`, `MultiPipelineReport`, `StorageInfo`, `_ProcessResult` dataclasses used to report ingestion stats (files processed, nodes/edges created, resolution rate, duration, etc.).

### `resolution/` — entity resolution

- **`entity_resolver.py`** — `EntityResolver`: rewrites unresolved edge `target_id`s (raw symbol names like `"charge"`) into real node ids, using four layered strategies in order — same-file lookup, symbol table, project-wide name index, and partial-id matching — preferring functions over classes over modules over variables on ties. Never mutates node/edge ids, and isolates per-edge failures into a `ResolutionReport`.
- **`builtins_catalog.py`** — static catalogs (`BUILTIN_FUNCTIONS`, `BUILTIN_METHODS`, `BUILTIN_EXCEPTIONS`, `BUILTIN_BASE_CLASSES`, `BUILTIN_DECORATORS`, `KNOWN_STDLIB_MODULES`) so the resolver can recognize (and not misresolve) references to Python builtins and the standard library.

### `semantic/` — enrichment

Both passes are optional and run after ingestion, before diagnosis.

- **`git_enricher.py`** — hits the GitHub commits API (`GET /repos/{owner}/{repo}/commits?path=...`) per file and attaches the latest commit's message/date/author/SHA to each node in that file. Rate-limit aware (per-path caching, backoff/retry on 403/429), stdlib `urllib` only.
- **`tfidf_enricher.py`** — builds a from-scratch TF-IDF index over a synthesized document per node (name, type, docstring, params/bases/decorators, neighbor names). Powers `search()` for free-text incident queries that have no stack frames to exact-match against. `save()`/`load()` round-trip the index to JSON.

### `diagnosis/` — the diagnosis pipeline

This is the runtime query path, orchestrated by `IncidentEngine`.

- **`stack_trace_parser.py`** — `StackTraceParser.parse(raw_text) -> ParsedIncident`. Accepts clean tracebacks, log-prefixed output, chained exceptions, or partial/truncated traces, and never crashes on malformed input. Extracts `error_type`, `error_message`, stack `frames`, and noise-filtered `keywords`.
- **`frame_parsers.py`** — per-language regexes/parsers (`PARSER_REGISTRY`, `PY_FRAME_RE`) that turn one raw traceback line into a `StackFrame` (file, line, function name).
- **`language_detector.py`** — Chain-of-Responsibility detector (`detect_language(text)`) that identifies which language a trace came from; only Python is implemented, JS/Java/Go/Ruby links are stubs that defer through to `"unknown"`.
- **`traversal_engine.py`** — the graph-search core:
  - `find_entry_nodes`: exact name+file+line-proximity matching against stack frames (TF-IDF is deliberately *not* used when frames exist — exact matching is strictly more precise); falls back to `tfidf_enricher` semantic search for frame-less, free-text incidents.
  - `traverse`: backward BFS over `CALLS`/`IMPORTS`/`EXTENDS` edges up to `max_hops`, with a beam width of 15 per level (keeps only the top-scored 15 candidates at each hop to stay bounded on large graphs). Forced to 0 hops for free-text incidents, since TF-IDF entry nodes are already the candidates.
  - `_evaluate_node`: scores every visited node on five signals — proximity to the crash site, git recency, keyword match, direct `RAISES` edge to the incident's error type, and (entry nodes only) outgoing-call connectivity — combined via configurable weights.
- **`verifier.py`** — `Verifier.verify_candidates`: independently re-checks the top-N scored candidates against three criteria — a structural path back to an entry node, git-recency confirmation, and keyword alignment — and derives a `high`/`medium`/`low` confidence level from how many checks pass (a missing structural path always invalidates the candidate, regardless of the other two). Also produces an `explanation_context` string, pre-formatted for handing to an LLM.
- **`incident_engine.py`** — `IncidentEngine.diagnose()`: wires parse → find-entry-nodes → traverse → verify into one call, returning a flat `DiagnosisReport` dataclass. Pure orchestration, no I/O, and designed to never raise — any internal failure is captured into `no_result_reason` instead.
- **`scoring_config.py`** — `ScoringWeights` / `DEFAULT_WEIGHTS`: the tunable weights (proximity, git, keyword, error_type, connectivity) used by the traversal scorer.
- **`scoring_utils.py`** — shared helpers: `days_since_iso` (git-recency math) and `matched_keywords` (keyword-overlap matching against name/docstring/commit message).

### `storage/`, `tools/`, `tests/`

- **`storage/verify_storage.py`** — validates a persisted graph (pickle/JSON) round-trips and is structurally sound before it's used for diagnosis.
- **`tools/visualize_graph.py`** — renders a knowledge graph for visual inspection; `tools/output/` holds generated artifacts.
- **`tests/test_traversal.py`** — unit tests for `TraversalEngine`.
- **`tests/full_pipeline_proof.py`** — an end-to-end smoke test exercising ingestion → enrichment → diagnosis on a real (small) codebase.

---

## Usage

**1. Build a knowledge graph from a repository:**

```bash
python3 src/ingestion/pipeline.py <repo_path> [output_dir]
```

This writes a pickled `Graph` (and a JSON mirror) to `output_dir` (default `./output`).

**2. (Optional) Enrich the graph** with git history and/or a TF-IDF search index using `semantic/git_enricher.py` and `semantic/tfidf_enricher.py` against the pickled graph.

**3. Diagnose an incident:**

```bash
PYTHONPATH=src python3 src/diagnose.py \
    --graph <path_to_graph.pkl> \
    --trace <path_to_trace.txt_OR_raw_trace_string> \
    [--tfidf <path_to_tfidf.json>] \
    [--hops 4] \
    [--top 5]
```

Example output shape:

```
=== Incident Diagnostics Engine ===

Incident:
  error_type:    AttributeError
  error_message: NoneType object has no attribute total
  keywords:      [...]
  frames:        3

Pipeline:
  entry nodes found: 1
  candidates found:  6
  nodes visited:     9

===============================
DIAGNOSIS
===============================

  Root cause:    charge  (payment.py)
  Confidence:    high
  Checks passed: ['path_exists', 'git_confirms', 'keyword_match']
  Checks failed: []
  Hops from entry: 2

  Reasons:
    - Modified 2 days ago: fix null check on cart total
    - Keyword match: total, cart

  Git evidence: fix null check on cart total (2026-09-01)

===============================
  Root cause identified with HIGH confidence.
  Inspect charge in payment.py.
===============================
```

`--trace` accepts either a path to a `.txt` file or a raw trace string passed directly on the command line.

---

## Scoring & confidence model

**Traversal score** (per candidate node, `traversal_engine.py`) is a weighted sum of:

| Signal | What it measures | Notes |
|---|---|---|
| Proximity | `1 / (1 + hops_from_entry)` | Closer to the crash site scores higher |
| Git recency | Days since last commit to the node | ≤1 day → 1.0, ≤7 → 0.8, ≤30 → 0.5, else 0.2 |
| Keyword match | Fraction of incident keywords found in name/docstring/commit message | 0 if no incident keywords |
| Error-type alignment | 1.0 if the node has an outgoing `RAISES` edge to the incident's error type, else 0 | No text-based fallback — edge-only |
| Connectivity | Outgoing `CALLS` count / 10, capped at 1.0 | Entry nodes only — noise at deeper hops |

**Verification confidence** (`verifier.py`) then re-checks the top-N candidates independently:

| Checks passed | Confidence | Valid? |
|---|---|---|
| 3 (path + git + keyword) | high | yes |
| 2 | medium | yes |
| 1 | low | yes |
| 0, or `path_exists` failed | low | **no** |

A structural path from the candidate back to an entry node is mandatory — a candidate that fails it is never marked valid, however well it scored elsewhere.

---

## Design principles

- **Never crash.** Every stage — trace parsing, traversal, verification, the top-level `IncidentEngine.diagnose()` — catches its own exceptions and degrades to an empty/failure result rather than propagating.
- **No external NLP/ML/parsing dependencies.** Tokenizing, parsing, TF-IDF, and scoring are all plain Python and the standard library.
- **Language-agnostic core, language-specific plugins.** `graph/`, `diagnosis/`, and `ingestion/pipeline.py` know nothing about Python specifically; all Python-specific logic lives behind `parser/python/` and `ingestion/language_strategy.py`'s `PythonStrategy`, so adding a new language means adding a new strategy, not touching the core.
- **Deterministic ordering.** Ties in scoring/beam-selection are always broken by a stable secondary key (node id), so traversal results don't depend on dict/set iteration order across runs.
- **Exact match first, semantic search as fallback.** Stack traces get exact name/file/line matching; TF-IDF semantic search only kicks in for frame-less, natural-language incident descriptions.
