"""Knowledge graph builder — interactive CLI demo.

Takes a GitHub repo URL, runs it through the full pipeline:
  1. Clone + AST parse  (IngestionPipeline)
  2. Git enrichment     (GitEnricher — GitHub API)
  3. TF-IDF indexing    (TFIDFEnricher — local, no network)

Prints rich terminal output at every step and ends with a complete
summary showing the graph path and all stats.

Usage:
    python build_graph_demo.py https://github.com/owner/repo
    python build_graph_demo.py https://github.com/owner/repo --token ghp_xxx
    python build_graph_demo.py          # prompts for URL interactively
"""

import argparse
import os
import pickle
import sys
import time

# ── make src/ importable ─────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, "src")
for _p in (ROOT, SRC):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ingestion.pipeline import IngestionPipeline       # noqa: E402
from semantic.git_enricher import GitEnricher          # noqa: E402
from semantic.tfidf_enricher import TFIDFEnricher      # noqa: E402

# ── display helpers ──────────────────────────────────────────────────────────
W = 72

def banner(title: str, char: str = "═") -> None:
    print("\n" + char * W)
    print(f"  {title}")
    print(char * W)

def section(title: str) -> None:
    print(f"\n  ── {title} " + "─" * max(0, W - len(title) - 6))

def ok(msg: str)   -> None: print(f"  ✓  {msg}")
def info(msg: str) -> None: print(f"     {msg}")
def warn(msg: str) -> None: print(f"  ⚠  {msg}")
def err(msg: str)  -> None: print(f"  ✗  {msg}")


# ── URL helpers ───────────────────────────────────────────────────────────────

def _parse_github_url(url: str):
    """Return (owner, repo) from a GitHub URL, or (None, None)."""
    url = url.rstrip("/").replace(".git", "")
    parts = url.replace("https://github.com/", "").replace("http://github.com/", "").split("/")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None, None


# ── Main ──────────────────────────────────────────────────────────────────────

def build(repo_url: str, github_token: str = "", output_dir: str = "./output") -> None:
    t_total = time.time()

    banner(f"Knowledge Graph Builder")
    info(f"repo   : {repo_url}")
    info(f"output : {output_dir}")
    info(f"token  : {'provided' if github_token else 'not provided (60 req/hr rate limit)'}")

    # ── Phase 1: Clone + AST parse + entity resolution ───────────────────────
    banner("Phase 1 — Clone · Parse · Resolve", char="─")

    pipeline = IngestionPipeline(output_dir=output_dir)
    t1 = time.time()
    report = pipeline.run(repo_url)
    t1_elapsed = time.time() - t1

    if report.errors and not report.output_pickle_path:
        err("Pipeline failed:")
        for e in report.errors:
            err("  " + e)
        sys.exit(1)

    ok(f"Cloned and parsed in {t1_elapsed:.1f}s")
    info(f"files discovered  : {report.total_files_discovered}")
    info(f"files parsed ok   : {report.files_processed_successfully}")
    info(f"files failed      : {report.files_failed}")
    info(f"nodes built       : {report.total_nodes}")
    info(f"edges built       : {report.total_edges}")
    info(f"resolution rate   : {report.resolution_rate:.1%}")
    info(f"graph pkl         : {report.output_pickle_path}")
    info(f"graph json        : {report.output_json_path}")

    if not report.output_pickle_path or not os.path.exists(report.output_pickle_path):
        err("Pickle not written — aborting enrichment steps.")
        sys.exit(1)

    pickle_path = report.output_pickle_path
    tfidf_path  = pickle_path.replace("_graph.pkl", "_tfidf.json")

    # Load graph for enrichment steps
    with open(pickle_path, "rb") as fh:
        graph = pickle.load(fh)

    # ── Phase 2: Git enrichment ───────────────────────────────────────────────
    banner("Phase 2 — Git Enrichment (GitHub API)", char="─")

    owner, repo = _parse_github_url(repo_url)
    if not owner:
        warn("Cannot parse owner/repo from URL — skipping git enrichment.")
        git_report = None
    else:
        info(f"querying github.com/{owner}/{repo}")
        if not github_token:
            warn("No token — unauthenticated API (60 req/hr). Pass --token to speed this up.")

        t2 = time.time()
        enricher = GitEnricher(github_token=github_token)

        # repo_root: the local clone path so file paths can be relativised
        clone_root = os.path.join(output_dir, "clones", repo)
        repo_root  = clone_root if os.path.isdir(clone_root) else None

        git_report = enricher.enrich(graph, owner, repo, repo_root=repo_root)
        t2_elapsed = time.time() - t2

        if git_report.api_errors:
            warn(f"{git_report.api_errors} API error(s) during enrichment")
            for e in git_report.errors[:5]:
                warn("  " + e)

        ok(f"Git enrichment done in {t2_elapsed:.1f}s")
        info(f"nodes enriched    : {git_report.nodes_enriched} / {git_report.total_nodes}")
        info(f"files queried     : {git_report.files_queried}")
        info(f"api errors        : {git_report.api_errors}")

        # Re-save graph with git metadata
        with open(pickle_path, "wb") as fh:
            pickle.dump(graph, fh)
        ok(f"Graph re-saved with git metadata → {pickle_path}")

    # ── Phase 3: TF-IDF indexing ──────────────────────────────────────────────
    banner("Phase 3 — TF-IDF Semantic Index", char="─")

    t3 = time.time()
    tfidf = TFIDFEnricher()
    tfidf_report = tfidf.enrich(graph)
    tfidf.save(tfidf_path)
    t3_elapsed = time.time() - t3

    ok(f"TF-IDF index built in {t3_elapsed:.1f}s")
    info(f"nodes indexed     : {tfidf_report.nodes_enriched}")
    info(f"vocabulary size   : {tfidf_report.vocabulary_size}")
    info(f"index saved       : {tfidf_path}")

    # ── Final summary ─────────────────────────────────────────────────────────
    t_elapsed = time.time() - t_total
    banner("Summary", char="═")

    print(f"""
  Repository       {repo_url}
  ─────────────────────────────────────────────────────────────
  Graph nodes      {report.total_nodes}
  Graph edges      {report.total_edges}
  Resolution rate  {report.resolution_rate:.1%}
  ─────────────────────────────────────────────────────────────
  Git enriched     {git_report.nodes_enriched if git_report else 'skipped'} nodes
  TF-IDF indexed   {tfidf_report.nodes_enriched} nodes  ·  vocab {tfidf_report.vocabulary_size}
  ─────────────────────────────────────────────────────────────
  Graph pickle     {pickle_path}
  Graph JSON       {report.output_json_path or '—'}
  TF-IDF index     {tfidf_path}
  ─────────────────────────────────────────────────────────────
  Total time       {t_elapsed:.1f}s
""")

    print("  To add this graph to the web app, add the following entry")
    print("  to the GRAPHS dict in demo_app/diagnose_service.py:\n")
    graph_key = os.path.basename(pickle_path).replace("_graph.pkl", "")
    print(f'    "{graph_key}": {{')
    print(f'        "label":   "{graph_key.replace("-","_").title()}",')
    print(f'        "pkl":     os.path.join(ROOT, "{pickle_path}"),')
    print(f'        "tfidf":   os.path.join(ROOT, "{tfidf_path}"),')
    print(f'        "presets": {{}},')
    print(f'        "seed":    False,')
    print( '    },')
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a knowledge graph from a GitHub repo.")
    parser.add_argument("url",     nargs="?",      help="GitHub repo URL")
    parser.add_argument("--token", default="",     help="GitHub personal access token")
    parser.add_argument("--output", default="./output", help="Output directory (default: ./output)")
    args = parser.parse_args()

    repo_url = args.url
    if not repo_url:
        repo_url = input("\n  Enter GitHub repo URL: ").strip()
    if not repo_url:
        err("No URL provided.")
        sys.exit(1)

    build(repo_url, github_token=args.token, output_dir=args.output)
