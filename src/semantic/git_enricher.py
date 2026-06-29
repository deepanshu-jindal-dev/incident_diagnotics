"""Git-history enrichment via the GitHub commits API.

For every distinct `file_path` in the graph, hit
`GET /repos/{owner}/{repo}/commits?path=...&per_page=5` and attach the
most recent commit's message / date / author / short-SHA to each node
that lives in that file. Uses only `urllib` from the standard library.

Rate-limit posture:
  - 0.1 s sleep between calls.
  - Per-path response cache so a 100-method file costs 1 API call.
  - On HTTP 403 / 429, sleep 5 s and retry **once**.
  - On HTTP 404, treat the file as having no commits (empty list).
  - Any other error becomes an `api_errors` increment in the report.
"""

import json
import os
import pickle
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Make `src/` importable so pickled `Graph` objects load correctly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


@dataclass
class GitEnrichmentReport:
    total_nodes: int = 0
    nodes_enriched: int = 0
    files_queried: int = 0
    api_errors: int = 0
    errors: List[str] = field(default_factory=list)


class GitEnricher:
    """Attach last-commit metadata to every node via the GitHub API.

    The constructor optionally accepts a personal access token. With a
    token the rate limit jumps from 60 to 5000 requests/hour, which
    matters as soon as a repo has more than ~50 distinct files.
    """

    def __init__(self, github_token: Optional[str] = None) -> None:
        self._token = github_token or os.environ.get("GITHUB_TOKEN", "")
        self._base_url = "https://api.github.com"
        # Cache of `api_file_path -> list of commit dicts`. Avoids
        # paying for the same file twice — even within one run, two
        # nodes from the same file would otherwise both hit the API.
        self._cache: Dict[str, Any] = {}

    # ---- main entry point -------------------------------------------

    def enrich(
        self, graph: Any, owner: str, repo: str,
        repo_root: Optional[str] = None,
        node_ids: Optional[List[str]] = None,
    ) -> GitEnrichmentReport:
        report = GitEnrichmentReport()
        nodes = graph.all_nodes()
        if node_ids is not None:
            node_id_set = set(node_ids)
            nodes = [n for n in nodes if n.id in node_id_set]
        report.total_nodes = len(nodes)

        if repo_root is None:
            repo_root = self._infer_repo_root(nodes, repo)

        # Build the file → most-recent-commit map by querying each
        # unique file once.
        unique_files = sorted({n.file_path for n in nodes if n.file_path})
        commit_by_local_path: Dict[str, Dict[str, Any]] = {}
        for local_path in unique_files:
            api_path = self._extract_file_path_for_api(local_path, repo_root)
            try:
                commits = self._get_commits_for_file(owner, repo, api_path)
            except Exception as ex:
                report.api_errors += 1
                report.errors.append(
                    "API call failed for " + api_path + ": " + repr(ex)
                )
                continue
            if commits:
                commit_by_local_path[local_path] = commits[0]
                report.files_queried += 1
            time.sleep(0.1)

        # Decorate every node whose file we have a commit for.
        for node in nodes:
            commit = commit_by_local_path.get(node.file_path)
            if commit is None:
                continue
            try:
                meta = self._extract_commit_metadata(commit)
                if not isinstance(node.metadata, dict):
                    node.metadata = {}
                node.metadata.update(meta)
                report.nodes_enriched += 1
            except Exception as ex:
                report.errors.append(
                    "metadata update failed for " + node.id + ": " + repr(ex)
                )

        return report

    def save_graph(self, graph: Any, pickle_path: str) -> None:
        """Re-save the graph with git metadata attached to nodes.

        Must be called after enrich() to persist commit metadata
        to disk. Without this call git metadata only exists in memory.
        """
        import pickle as _pickle

        # Save pickle
        with open(pickle_path, "wb") as fh:
            _pickle.dump(graph, fh)

        # Save JSON alongside pickle
        json_path = pickle_path.replace(".pkl", ".json")
        try:
            graph.serialize_to_json(json_path)
        except Exception as ex:
            print("Warning: JSON save failed: " + repr(ex))

    # ---- HTTP plumbing ----------------------------------------------

    def _get_commits_for_file(
        self, owner: str, repo: str, file_path: str,
    ) -> List[Dict[str, Any]]:
        if file_path in self._cache:
            return self._cache[file_path]

        query = urllib.parse.urlencode({"path": file_path, "per_page": 5})
        url = self._base_url + "/repos/" + owner + "/" + repo + "/commits?" + query
        data = self._make_request(url)
        if not isinstance(data, list):
            # None means a transient error — do not cache so the next
            # call retries the API instead of reusing a stale failure.
            return []
        self._cache[file_path] = data
        return data

    def _make_request(self, url: str) -> Optional[Any]:
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self._token:
            headers["Authorization"] = "token " + self._token

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as ex:
            if ex.code in (403, 429):
                # Likely rate-limited; back off and try once more.
                time.sleep(5)
                try:
                    req2 = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req2, timeout=10) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except Exception:
                    return None
            if ex.code == 404:
                # File / repo not on GitHub — return an empty list so
                # the caller treats it as "no commits" rather than as
                # an error.
                return []
            return None
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            return None

    # ---- path / metadata helpers -------------------------------------

    def _extract_file_path_for_api(
        self, node_file_path: str, repo_root: str,
    ) -> str:
        p = (node_file_path or "").replace("\\", "/")
        if repo_root:
            rr = repo_root.replace("\\", "/")
            if not rr.endswith("/"):
                rr += "/"
            if p.startswith(rr):
                p = p[len(rr):]
        return p.lstrip("/")

    def _infer_repo_root(self, nodes: List[Any], repo: str) -> str:
        """Best-effort guess at the local clone root when the caller
        didn't supply one. Looks for `/{repo}/` in the first file path
        that has one, otherwise falls back to the common prefix."""
        needle = "/" + repo + "/"
        for node in nodes:
            if not node.file_path:
                continue
            p = node.file_path.replace("\\", "/")
            idx = p.find(needle)
            if idx != -1:
                return p[:idx + len(needle)]
        # Fallback: common prefix of every file path we know about.
        # os.path.commonpath on a multi-repo merged graph would return a
        # directory ancestor of ALL repos, stripping too much.  Limit to
        # the dirname of the first available path as a best-effort guess.
        paths = [n.file_path.replace("\\", "/") for n in nodes if n.file_path]
        if not paths:
            return ""
        return os.path.dirname(paths[0])

    def _extract_commit_metadata(self, commit: Dict[str, Any]) -> Dict[str, Any]:
        commit_obj = commit.get("commit") or {}
        author = commit_obj.get("author") or {}
        committer = commit_obj.get("committer") or {}
        sha = commit.get("sha") or ""
        # Prefer committer.date — it reflects when the commit actually
        # landed (merge/push time).  author.date is when the patch was
        # originally written and can be arbitrarily old for cherry-picks
        # or merge commits, causing the recency check to return False.
        date = committer.get("date", "") or author.get("date", "") or ""
        return {
            "last_commit_message": commit_obj.get("message", "") or "",
            "last_commit_date": date,
            "last_commit_author": author.get("name", "") or "",
            "last_commit_sha": sha[:7] if sha else "",
        }


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python git_enricher.py <pickle_path> <owner> <repo> [token]")
        sys.exit(1)

    pickle_path = sys.argv[1]
    owner = sys.argv[2]
    repo = sys.argv[3]
    token = sys.argv[4] if len(sys.argv) > 4 else None

    with open(pickle_path, "rb") as fh:
        graph = pickle.load(fh)

    enricher = GitEnricher(github_token=token)
    report = enricher.enrich(graph, owner, repo)

    print("Enriched " + str(report.nodes_enriched) + "/" + str(report.total_nodes) + " nodes")
    print("Files queried: " + str(report.files_queried))
    print("API errors:    " + str(report.api_errors))

    # Re-save graph with git metadata persisted
    print("Re-saving graph with git metadata...")
    enricher.save_graph(graph, pickle_path)
    print("Saved: " + pickle_path)

    if report.errors:
        print("\nErrors:")
        for err in report.errors[:10]:
            print("  - " + err)
