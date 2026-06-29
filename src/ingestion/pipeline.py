"""End-to-end ingestion pipeline.

Walks a repository on disk and produces a fully built, resolved, and
serialized knowledge graph. The pipeline is deliberately conservative
about failure: a bad file at any stage (read, tokenize, parse, walk)
is logged, its partial contributions are dropped, and processing
continues with the next file.

CLI:

    python pipeline.py <repo_path> [output_dir]
"""

import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

# Make `src/` importable so absolute imports work regardless of how
# this file is invoked (as a script, via `python -m`, or imported as
# part of the `ingestion` package).
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from graph.graph import Graph  # noqa: E402
from resolution.entity_resolver import EntityResolver, ResolutionReport  # noqa: E402

from ingestion.language_strategy import (  # noqa: E402
    LANGUAGE_REGISTRY,
    SUPPORTED_EXTENSIONS,
)
from ingestion.pipeline_reports import (  # noqa: E402
    MultiPipelineReport,
    PipelineReport,
    StorageInfo,
)


# Directories that should never be walked. Most are build artifacts,
# virtual envs, or VCS metadata that yield no useful source signal and
# may contain auto-generated code that confuses the parser.
SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".venv", "venv", "env",
    "node_modules", "dist", "build", ".tox", ".eggs",
})

# Files larger than this are almost certainly auto-generated (lockfiles
# encoded as `.py`, schema dumps, generated bindings). Skip them to
# keep ingestion bounded.
MAX_FILE_SIZE_BYTES = 1024 * 1024  # 1 MiB


# =====================================================================
# Pipeline
# =====================================================================


class IngestionPipeline:
    """Discover → tokenize → parse → walk → resolve → store.

    One instance can be reused across runs; per-run state is reset at
    the top of `run()`.
    """

    def __init__(self, output_dir: str = "./output") -> None:
        self._output_dir = output_dir
        # Per-run state, populated by run() and consumed by helpers.
        self._failed_files: List[str] = []
        self._errors: List[str] = []

    # ---- public entry point -----------------------------------------

    def run(self, repo_path: str) -> PipelineReport:
        start = time.time()
        self._failed_files = []
        self._errors = []

        original_path = repo_path
        try:
            repo_path, clone_root = self._clone_and_detect(repo_path)
        except Exception as ex:
            self._errors.append("Clone failed: " + repr(ex))
            return PipelineReport(
                repo_path=original_path,
                errors=list(self._errors),
                duration_seconds=time.time() - start,
            )

        graph = Graph()

        # Step 1 — discovery
        files = self._discover_files(repo_path)
        total = len(files)
        print("Discovered " + str(total) + " source files under " + repo_path)

        # Step 2 — per-file processing
        successes = 0
        for index, file_path in enumerate(files, start=1):
            ok = self._process_file(file_path, graph)
            if ok:
                successes += 1
                print("[" + str(index) + "/" + str(total) + "] " + file_path)
            else:
                last_error = self._errors[-1] if self._errors else "unknown error"
                print("[FAILED] " + file_path + ": " + last_error)

        # Step 3 — entity resolution
        print("\nResolving entities...")
        try:
            resolution_report = self._resolve(graph)
        except Exception as ex:
            # EntityResolver is supposed to swallow its own errors; if
            # it raises anyway, record and continue with an empty report.
            self._errors.append("entity resolution failed: " + repr(ex))
            resolution_report = ResolutionReport()

        # Step 4 — storage
        print("Writing graph to " + self._output_dir + "...")
        storage = self._store(graph, repo_path)

        end = time.time()
        report = PipelineReport(
            repo_path=original_path,
            total_files_discovered=total,
            files_processed_successfully=successes,
            files_failed=len(self._failed_files),
            total_nodes=graph.node_count,
            total_edges=graph.edge_count,
            resolution_rate=resolution_report.resolution_rate,
            output_json_path=storage.json_path,
            output_pickle_path=storage.pickle_path,
            failed_files=list(self._failed_files),
            errors=list(self._errors),
            duration_seconds=end - start,
        )
        self._print_summary(report, resolution_report)
        if storage.pickle_path:
            self._write_state(
                graph_name=self._graph_name(storage.pickle_path),
                pickle_path=storage.pickle_path,
                repos={clone_root: {
                    "last_hash": self._git_head_hash(clone_root),
                    "clone_url": original_path if self._is_url(original_path) else "",
                }},
            )
        return report

    def run_multi(self, repo_paths: List[str]) -> MultiPipelineReport:
        """Process multiple repositories and merge into one unified graph.

        Builds individual graphs for each repo, merges them, runs
        entity resolution on the merged graph, and stores the result.
        """
        start = time.time()
        multi_report = MultiPipelineReport(repo_paths=list(repo_paths))
        merged_graph = Graph()
        repos_state: Dict[str, Dict] = {}

        for repo_path in repo_paths:
            self._failed_files = []
            self._errors = []

            # Clone if URL
            original_path = repo_path
            try:
                repo_path, clone_root = self._clone_and_detect(repo_path)
            except Exception as ex:
                error_msg = "Clone failed for " + original_path + ": " + repr(ex)
                multi_report.errors.append(error_msg)
                print(error_msg)
                continue

            # Build per-repo graph
            per_repo_graph = Graph()
            files = self._discover_files(repo_path)
            total = len(files)
            print("\nProcessing " + original_path + " (" + str(total) + " files)")

            successes = 0
            for index, file_path in enumerate(files, start=1):
                ok = self._process_file(file_path, per_repo_graph)
                if ok:
                    successes += 1
                else:
                    last_error = self._errors[-1] if self._errors else "unknown"
                    print("[FAILED] " + file_path + ": " + last_error)

            # Build individual report
            individual = PipelineReport(
                repo_path=original_path,
                total_files_discovered=total,
                files_processed_successfully=successes,
                files_failed=len(self._failed_files),
                total_nodes=per_repo_graph.node_count,
                total_edges=per_repo_graph.edge_count,
                failed_files=list(self._failed_files),
                errors=list(self._errors),
            )
            multi_report.individual_reports.append(individual)
            multi_report.total_files_discovered += total
            multi_report.total_files_processed += successes

            # Merge into unified graph
            self._merge_into(merged_graph, per_repo_graph)
            print(
                "Merged: " + str(per_repo_graph.node_count) + " nodes, "
                + str(per_repo_graph.edge_count) + " edges"
            )
            repos_state[clone_root] = {
                "last_hash": self._git_head_hash(clone_root),
                "clone_url": original_path if self._is_url(original_path) else "",
            }

        # Run entity resolution on merged graph
        print("\nResolving entities across all repositories...")
        try:
            resolution_report = self._resolve(merged_graph)
        except Exception as ex:
            multi_report.errors.append("Resolution failed: " + repr(ex))
            resolution_report = ResolutionReport()

        # Store merged graph
        print("Writing merged graph to " + self._output_dir + "...")
        storage = self._store(merged_graph, "merged")

        end = time.time()
        multi_report.total_nodes = merged_graph.node_count
        multi_report.total_edges = merged_graph.edge_count
        multi_report.resolution_rate = resolution_report.resolution_rate
        multi_report.output_json_path = storage.json_path
        multi_report.output_pickle_path = storage.pickle_path
        multi_report.duration_seconds = end - start
        multi_report.errors.extend(self._errors)

        self._print_multi_summary(multi_report, resolution_report)
        if storage.pickle_path:
            self._write_state(
                graph_name=self._graph_name(storage.pickle_path),
                pickle_path=storage.pickle_path,
                repos=repos_state,
            )
        return multi_report

    # ---- URL / remote-repo helpers ---------------------------------

    def _is_url(self, path: str) -> bool:
        """Check if the given path is a remote URL."""
        return (
            path.startswith("http://")
            or path.startswith("https://")
            or path.startswith("git@")
        )

    def _clone_repo(self, url: str) -> str:
        """Clone a remote repository locally using git.

        Uses --depth=1 shallow clone for speed. Caches the clone
        so running the same URL twice skips the network call.
        Only caches on successful clone — failed clones are cleaned up.
        Returns the local path of the cloned repository.
        """
        repo_name = url.rstrip("/").split("/")[-1].replace(".git", "")
        clone_dir = os.path.join(self._output_dir, "clones", repo_name)

        if os.path.exists(clone_dir):
            if any(os.scandir(clone_dir)):
                print("Using cached clone at " + clone_dir)
                return clone_dir
            else:
                print("Cached clone is empty, re-cloning...")
                shutil.rmtree(clone_dir, ignore_errors=True)

        os.makedirs(clone_dir, exist_ok=True)
        print("Cloning " + url + " ...")
        result = subprocess.run(
            ["git", "clone", "--depth=1", url, clone_dir],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            shutil.rmtree(clone_dir, ignore_errors=True)
            raise RuntimeError("Git clone failed:\n" + result.stderr)

        print("Cloned to " + clone_dir)
        return clone_dir

    def _clone_and_detect(self, repo_path: str) -> Tuple[str, str]:
        """Resolve a repo argument to (source_dir, clone_root).

        For a URL, clone it and auto-detect the densest source subdir,
        returning that subdir plus the clone root (used for git state
        tracking). For a local path, return it unchanged as (path, path).
        Raises on clone failure so each caller records the error its own way.
        """
        if not self._is_url(repo_path):
            return repo_path, repo_path
        clone_root = self._clone_repo(repo_path)
        src_dir = self._auto_detect_src_dir(clone_root)
        print("Source directory: " + src_dir)
        return src_dir, clone_root

    def _auto_detect_src_dir(self, repo_path: str) -> str:
        """Find the subdirectory with the highest density of source files.

        Skips common non-source directories like tests, docs, examples.
        Falls back to repo_path itself if nothing better is found.
        """
        skip_names = frozenset({
            "test", "tests", "doc", "docs",
            "example", "examples", "bench", "benchmarks",
            "scripts", "tools", "build", "dist",
        })
        best_dir = repo_path
        best_count = 0

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            rel = os.path.relpath(root, repo_path)
            parts = set(rel.replace("\\", "/").split("/"))
            if parts & skip_names:
                continue
            src_count = sum(
                1 for f in files
                if os.path.splitext(f)[1].lower() in SUPPORTED_EXTENSIONS
            )
            if src_count > best_count:
                best_count = src_count
                best_dir = root

        return best_dir

    # ---- Step 1: discovery ------------------------------------------

    def _discover_files(self, repo_path: str) -> List[str]:
        """Recursively find every source file whose extension is in
        LANGUAGE_REGISTRY under `repo_path`. Skipped directories are
        pruned in-place from `os.walk`'s dirs list so we never descend
        into them at all."""
        discovered: List[str] = []
        if not os.path.isdir(repo_path):
            self._errors.append("repo_path is not a directory: " + repo_path)
            return discovered

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in files:
                if os.path.splitext(fname)[1].lower() not in SUPPORTED_EXTENSIONS:
                    continue
                full = os.path.join(root, fname)
                try:
                    size = os.path.getsize(full)
                except OSError as ex:
                    self._errors.append("stat failed for " + full + ": " + repr(ex))
                    continue
                if size > MAX_FILE_SIZE_BYTES:
                    continue
                discovered.append(full)
        return sorted(discovered)

    # ---- Step 2: per-file processing --------------------------------

    def _process_file(self, file_path: str, graph: Graph) -> bool:
        """Read one file, dispatch to the language strategy, and merge the
        result into `graph` only on full success."""
        ext = os.path.splitext(file_path)[1].lower()
        strategy = LANGUAGE_REGISTRY.get(ext)
        if strategy is None:
            self._record_failure(file_path, "no handler for extension: " + ext)
            return False

        # Reading stays here — encoding fallback is a pipeline responsibility,
        # not a language-specific one.
        source = self._read_file_safe(file_path)
        if source is None:
            return False

        # Strategy owns tokenize → parse → walk via the builder internally.
        result = strategy.process(file_path, source)
        self._errors.extend(result.errors)
        self._failed_files.extend(result.failed_files)

        if result.graph is None:
            return False

        self._merge_into(graph, result.graph)
        return True

    def _read_file_safe(self, file_path: str) -> Optional[str]:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                return fh.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, "r", encoding="latin-1") as fh:
                    return fh.read()
            except Exception as ex:
                self._record_failure(file_path, "read (latin-1): " + repr(ex))
                return None
        except OSError as ex:
            self._record_failure(file_path, "read: " + repr(ex))
            return None
        except Exception as ex:
            self._record_failure(file_path, "read: " + repr(ex))
            return None

    def _merge_into(self, main: Graph, other: Graph) -> None:
        for node in other.all_nodes():
            if not main.has_node(node.id):
                main.add_node(node)
        for edge in other.all_edges():
            try:
                main.add_edge(edge)
            except Exception:
                # Theoretically possible if two files independently
                # produced the same (source, relationship, target) base
                # id. Drop the dupe — Walker already gave it a counter
                # suffix within its own file but not across files.
                continue

    def _record_failure(self, file_path: str, detail: str) -> None:
        self._failed_files.append(file_path)
        self._errors.append(file_path + ": " + detail)

    # ---- Step 3: resolution -----------------------------------------

    def _resolve(self, graph: Graph) -> ResolutionReport:
        return EntityResolver().resolve(graph)

    # ---- Step 4: storage --------------------------------------------

    def _store(self, graph: Graph, repo_path: str) -> StorageInfo:
        repo_name = os.path.basename(os.path.normpath(repo_path)) or "repo"
        repo_name = repo_name.replace(" ", "_")

        try:
            os.makedirs(self._output_dir, exist_ok=True)
        except Exception as ex:
            self._errors.append("mkdir " + self._output_dir + " failed: " + repr(ex))
            return StorageInfo(
                node_count=graph.node_count, edge_count=graph.edge_count,
            )

        json_path = os.path.join(self._output_dir, repo_name + "_graph.json")
        pickle_path = os.path.join(self._output_dir, repo_name + "_graph.pkl")

        json_written = ""
        pickle_written = ""

        try:
            graph.serialize_to_json(json_path)
            json_written = json_path
        except Exception as ex:
            self._errors.append("JSON write failed: " + repr(ex))

        try:
            with open(pickle_path, "wb") as fh:
                pickle.dump(graph, fh)
            pickle_written = pickle_path
        except Exception as ex:
            self._errors.append("pickle write failed: " + repr(ex))

        return StorageInfo(
            json_path=json_written,
            pickle_path=pickle_written,
            node_count=graph.node_count,
            edge_count=graph.edge_count,
        )

    # ---- incremental update -----------------------------------------

    def update(
        self, graph_name: str, github_token: Optional[str] = None,
    ) -> MultiPipelineReport:
        """Incrementally update an existing graph.

        Diffs each repo against its stored commit hash, removes stale
        nodes, reprocesses changed files, re-runs full entity resolution,
        applies partial git enrichment to new nodes only, and rebuilds
        the full TF-IDF index.
        """
        from semantic.git_enricher import GitEnricher
        from semantic.tfidf_enricher import TFIDFEnricher

        start = time.time()
        multi_report = MultiPipelineReport()
        self._failed_files = []
        self._errors = []

        # Load state ---------------------------------------------------
        state = self._read_state()
        if graph_name not in state:
            msg = (
                "Graph '" + graph_name + "' not found in " + self._state_path()
                + ". Run a full ingest first."
            )
            multi_report.errors.append(msg)
            print(msg)
            return multi_report

        graph_state = state[graph_name]
        pickle_path = graph_state.get("pickle_path", "")
        repos = graph_state.get("repos", {})

        if not pickle_path or not os.path.exists(pickle_path):
            msg = "Pickle not found: " + pickle_path
            multi_report.errors.append(msg)
            print(msg)
            return multi_report

        # Load existing graph ------------------------------------------
        print("Loading graph from " + pickle_path + "...")
        with open(pickle_path, "rb") as fh:
            graph = pickle.load(fh)
        print("  nodes: " + str(graph.node_count) + "  edges: " + str(graph.edge_count))

        # Find changed / deleted files per repo ------------------------
        changed_files: List[str] = []
        deleted_files: List[str] = []
        repos_updated = False

        for repo_path, repo_info in repos.items():
            last_hash = repo_info.get("last_hash", "")
            self._git_pull(repo_path)
            current_hash = self._git_head_hash(repo_path)

            if not current_hash:
                print("  [skip] cannot get HEAD for " + repo_path)
                continue
            if current_hash == last_hash:
                print("  [skip] no changes in " + os.path.basename(repo_path))
                continue

            print("\n  Checking " + os.path.basename(repo_path) + "...")
            ch = self._git_changed_files(repo_path, last_hash, current_hash)
            dl = self._git_deleted_files(repo_path, last_hash, current_hash)
            print("    changed: " + str(len(ch)) + "  deleted: " + str(len(dl)))

            changed_files.extend(ch)
            deleted_files.extend(dl)
            repos[repo_path]["last_hash"] = current_hash
            repos_updated = True

        if not changed_files and not deleted_files:
            if repos_updated:
                self._write_state(graph_name, pickle_path, repos)
            print("\nNothing to update.")
            return multi_report

        # Remove stale nodes -------------------------------------------
        total_removed = 0
        for fp in set(deleted_files + changed_files):
            total_removed += graph.remove_nodes_for_file(fp)
        print("\nRemoved " + str(total_removed) + " stale nodes")

        # Reprocess changed files → delta graph ------------------------
        delta_graph = Graph()
        self._failed_files = []
        self._errors = []
        for fp in changed_files:
            ok = self._process_file(fp, delta_graph)
            if not ok:
                last_err = self._errors[-1] if self._errors else "unknown"
                print("[FAILED] " + fp + ": " + last_err)
        print(
            "Delta graph: " + str(delta_graph.node_count)
            + " nodes from " + str(len(changed_files)) + " files"
        )

        # Nodes needing (re-)enrichment: both new files and changed files.
        delta_node_ids = [n.id for n in delta_graph.all_nodes()]

        # Merge delta → existing graph ---------------------------------
        self._merge_into(graph, delta_graph)
        print(
            "Merged: " + str(graph.node_count) + " nodes  "
            + str(graph.edge_count) + " edges"
        )

        # Full entity resolution ---------------------------------------
        print("\nResolving entities...")
        try:
            resolution_report = self._resolve(graph)
            print(
                "  resolved: " + str(resolution_report.resolved_count)
                + "  unresolved: " + str(resolution_report.unresolved_count)
            )
        except Exception as ex:
            self._errors.append("resolution failed: " + repr(ex))
            print("  resolution error: " + repr(ex))

        # Partial git enrichment (new nodes only) ----------------------
        enriched_count = 0
        if delta_node_ids:
            token = github_token or os.environ.get("GITHUB_TOKEN", "")
            for repo_path, repo_info in repos.items():
                owner, repo_name = self._extract_github_owner_repo(
                    repo_info.get("clone_url", "")
                )
                if not owner or not repo_name:
                    continue
                try:
                    git_enricher = GitEnricher(github_token=token)
                    git_report = git_enricher.enrich(
                        graph, owner, repo_name, node_ids=delta_node_ids,
                    )
                    enriched_count += git_report.nodes_enriched
                except Exception as ex:
                    self._errors.append(
                        "git enrichment failed for " + repo_path + ": " + repr(ex)
                    )
        if enriched_count:
            print("\nGit enrichment: " + str(enriched_count) + " nodes updated")
        else:
            print("\nGit enrichment: skipped (no GitHub token or non-GitHub repos)")

        # Full TF-IDF rebuild ------------------------------------------
        tfidf_path = pickle_path.replace("_graph.pkl", "_tfidf.json")
        print("\nRebuilding TF-IDF index...")
        try:
            tfidf_enricher = TFIDFEnricher()
            tfidf_report = tfidf_enricher.enrich(graph)
            tfidf_enricher.save(tfidf_path)
            print(
                "  indexed: " + str(tfidf_report.nodes_enriched)
                + " nodes  vocab: " + str(tfidf_report.vocabulary_size)
            )
        except Exception as ex:
            self._errors.append("tfidf rebuild failed: " + repr(ex))
            print("  tfidf error: " + repr(ex))

        # Save updated graph -------------------------------------------
        print("\nSaving updated graph...")
        storage = self._store(graph, graph_name)

        # Persist updated state ----------------------------------------
        self._write_state(graph_name, storage.pickle_path or pickle_path, repos)

        end = time.time()
        multi_report.total_nodes = graph.node_count
        multi_report.total_edges = graph.edge_count
        multi_report.output_pickle_path = storage.pickle_path
        multi_report.output_json_path = storage.json_path
        multi_report.duration_seconds = end - start
        multi_report.errors.extend(self._errors)

        print("\n=== Update Complete ===")
        print("nodes:    " + str(graph.node_count))
        print("edges:    " + str(graph.edge_count))
        print("duration: {:.2f}s".format(end - start))
        return multi_report

    # ---- state helpers ----------------------------------------------

    def _state_path(self) -> str:
        return os.path.join(self._output_dir, "ingestion_state.json")

    def _read_state(self) -> Dict:
        path = self._state_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _write_state(
        self, graph_name: str, pickle_path: str, repos: Dict,
    ) -> None:
        state = self._read_state()
        state[graph_name] = {"pickle_path": pickle_path, "repos": repos}
        try:
            with open(self._state_path(), "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
        except Exception as ex:
            self._errors.append("state write failed: " + repr(ex))

    def _graph_name(self, pickle_path: str) -> str:
        base = os.path.basename(pickle_path)
        return base.replace("_graph.pkl", "") or "graph"

    # ---- git helpers ------------------------------------------------

    def _git_pull(self, repo_path: str) -> bool:
        """Pull latest changes from remote. Returns True on success."""
        try:
            result = subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=repo_path, capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                print("  [pull] " + os.path.basename(repo_path) + ": " + result.stdout.strip())
                return True
            print("  [pull failed] " + os.path.basename(repo_path) + ": " + result.stderr.strip())
            return False
        except Exception as ex:
            print("  [pull error] " + repr(ex))
            return False

    def _git_head_hash(self, repo_path: str) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo_path, capture_output=True, text=True, timeout=10,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""

    def _git_diff_files(
        self, repo_path: str, old_hash: str, new_hash: str,
        diff_filter: str, require_exists: bool,
    ) -> List[str]:
        """Return the source files touched between two commits, filtered
        by git's `--diff-filter` (e.g. "AM" for added/modified, "D" for
        deleted). Only files with a supported extension are kept; when
        `require_exists` is True, files no longer on disk are dropped."""
        try:
            result = subprocess.run(
                ["git", "diff", old_hash, new_hash,
                 "--name-only", "--diff-filter=" + diff_filter],
                cwd=repo_path, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return []
            files = []
            for rel in result.stdout.strip().splitlines():
                if os.path.splitext(rel)[1].lower() not in SUPPORTED_EXTENSIONS:
                    continue
                full = os.path.normpath(os.path.join(repo_path, rel))
                if require_exists and not os.path.exists(full):
                    continue
                files.append(full)
            return files
        except Exception:
            return []

    def _git_changed_files(
        self, repo_path: str, old_hash: str, new_hash: str,
    ) -> List[str]:
        return self._git_diff_files(
            repo_path, old_hash, new_hash, "AM", require_exists=True,
        )

    def _git_deleted_files(
        self, repo_path: str, old_hash: str, new_hash: str,
    ) -> List[str]:
        return self._git_diff_files(
            repo_path, old_hash, new_hash, "D", require_exists=False,
        )

    def _extract_github_owner_repo(self, url: str) -> tuple:
        if not url or "github.com" not in url:
            return "", ""
        try:
            url = url.rstrip("/").replace(".git", "")
            if url.startswith("git@"):
                path = url.split(":", 1)[-1]
            else:
                path = url.split("github.com/", 1)[-1]
            parts = path.strip("/").split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
        except Exception:
            pass
        return "", ""

    # ---- summary ----------------------------------------------------

    def _print_summary(
        self, report: PipelineReport, resolution: ResolutionReport,
    ) -> None:
        print("")
        print("=== Pipeline Summary ===")
        print("repo:              " + report.repo_path)
        print("files discovered:  " + str(report.total_files_discovered))
        print("files succeeded:   " + str(report.files_processed_successfully))
        print("files failed:      " + str(report.files_failed))
        print("nodes:             " + str(report.total_nodes))
        print("edges:             " + str(report.total_edges))
        print("resolution rate:   {:.1%}".format(report.resolution_rate))
        print("  resolved edges:           " + str(resolution.resolved_count))
        print("  unresolved (project):     " + str(resolution.unresolved_count))
        print("  builtin/stdlib (tagged):  " + str(resolution.builtin_count))
        print("  imports (out of scope):   " + str(getattr(resolution, "imports_count", 0)))
        print("  skipped (CONTAINS):       " + str(resolution.skipped_count))
        print("JSON output:       " + (report.output_json_path or "<not written>"))
        print("pickle output:     " + (report.output_pickle_path or "<not written>"))
        print("duration:          {:.2f}s".format(report.duration_seconds))
        if report.failed_files:
            print("failed files (" + str(len(report.failed_files)) + "):")
            for fp in report.failed_files[:10]:
                print("  - " + fp)
            if len(report.failed_files) > 10:
                print("  ... +" + str(len(report.failed_files) - 10) + " more")

    def _print_multi_summary(
        self, report: MultiPipelineReport, resolution: ResolutionReport
    ) -> None:
        print("\n=== Multi-Repository Pipeline Summary ===")
        print("repositories:      " + str(len(report.repo_paths)))
        for r in report.individual_reports:
            print(
                "  " + r.repo_path + " → " + str(r.total_nodes)
                + " nodes, " + str(r.total_edges) + " edges"
            )
        print("total files:       " + str(report.total_files_discovered))
        print("total succeeded:   " + str(report.total_files_processed))
        print("merged nodes:      " + str(report.total_nodes))
        print("merged edges:      " + str(report.total_edges))
        print("resolution rate:   {:.1%}".format(report.resolution_rate))
        print("  resolved:          " + str(resolution.resolved_count))
        print("  unresolved:        " + str(resolution.unresolved_count))
        print("  builtin tagged:    " + str(resolution.builtin_count))
        print("JSON output:       " + (report.output_json_path or "<not written>"))
        print("pickle output:     " + (report.output_pickle_path or "<not written>"))
        print("duration:          {:.2f}s".format(report.duration_seconds))


# =====================================================================
# CLI entry
# =====================================================================


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <repo_path_or_url> [repo2 ...] [--output dir]")
        print("       python pipeline.py --update <graph_name> [--output dir] [--token <github_token>]")
        sys.exit(1)

    output_dir = "./output"
    repos: List[str] = []
    update_name: str = ""
    github_token: str = ""

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--output" and i + 1 < len(sys.argv):
            output_dir = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--update" and i + 1 < len(sys.argv):
            update_name = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--token" and i + 1 < len(sys.argv):
            github_token = sys.argv[i + 1]
            i += 2
        else:
            repos.append(sys.argv[i])
            i += 1

    pipeline = IngestionPipeline(output_dir=output_dir)

    if update_name:
        report = pipeline.update(update_name, github_token=github_token or None)
        print("\nDone in {:.1f}s".format(report.duration_seconds))
    elif len(repos) == 1:
        report = pipeline.run(repos[0])
        print("\nDone in {:.1f}s".format(report.duration_seconds))
        print("Nodes: " + str(report.total_nodes))
        print("Edges: " + str(report.total_edges))
        print("Resolution rate: {:.1%}".format(report.resolution_rate))
    else:
        report = pipeline.run_multi(repos)
        print("\nDone in {:.1f}s".format(report.duration_seconds))
        print("Merged nodes: " + str(report.total_nodes))
        print("Merged edges: " + str(report.total_edges))
        print("Resolution rate: {:.1%}".format(report.resolution_rate))
