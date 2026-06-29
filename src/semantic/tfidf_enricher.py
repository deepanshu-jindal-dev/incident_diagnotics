"""TF-IDF semantic enrichment for the code knowledge graph.

For each `Node` in the graph this builds a small descriptive document
(name, type, docstring, params/bases/decorators, immediate neighbor
names), tokenizes it, and produces a sparse TF-IDF vector. Vectors are
stored both on `node.metadata["tfidf_vector"]` for in-graph use and
inside the enricher's own indexes for `search()` / `save()`.

Implementation is from-scratch arithmetic over Python `dict`s — no
sklearn, no numpy, no external libraries.
"""

import json
import math
import os
import pickle
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Make `src/` importable so pickled `Graph` objects (which reference
# `graph.graph.Graph`, `graph.node.Node`, etc.) load correctly when this
# file is invoked as a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)


# Splits on every run of non-alphanumeric characters — including `_`,
# so identifiers like `place_order` decompose into `place` + `order`.
_TOKEN_SPLIT_RE = re.compile(r"[^a-zA-Z0-9]+")

STOP_WORDS = frozenset({
    "the", "a", "an", "is", "it", "in", "of", "to", "for",
    "and", "or", "not", "be", "as", "at", "by", "do", "if",
    "on", "up", "we",
})


@dataclass
class EnrichmentReport:
    total_nodes: int = 0
    nodes_enriched: int = 0
    vocabulary_size: int = 0
    avg_vector_length: float = 0.0
    errors: List[str] = field(default_factory=list)


class TFIDFEnricher:
    """Computes TF-IDF vectors for every node in a `Graph`.

    State after `enrich(graph)`:

      - `self._idf`            term → idf
      - `self._node_vectors`   node id → {term: tfidf}
      - `self._node_texts`     node id → raw descriptive text

    Both `search()` and `save()` read this state, so do not reuse a
    populated enricher across different graphs without re-running
    `enrich()` first.
    """

    def __init__(self) -> None:
        self._idf: Dict[str, float] = {}
        self._node_vectors: Dict[str, Dict[str, float]] = {}
        self._node_texts: Dict[str, str] = {}

    # ---- main entry points -----------------------------------------

    def enrich(self, graph: Any) -> EnrichmentReport:
        report = EnrichmentReport()
        nodes = graph.all_nodes()
        report.total_nodes = len(nodes)

        # Phase 1: build text + token list for every node. Errors per
        # node are absorbed into the report so one weird node can't
        # poison the whole pass.
        token_lists: Dict[str, List[str]] = {}
        for node in nodes:
            try:
                text = self._build_node_text(node, graph)
                self._node_texts[node.id] = text
                token_lists[node.id] = self._tokenize(text)
            except Exception as ex:
                report.errors.append(
                    "text build failed for " + node.id + ": " + repr(ex)
                )
                self._node_texts[node.id] = ""
                token_lists[node.id] = []

        # Phase 2: IDF over the whole corpus.
        self._idf = self._compute_idf(list(token_lists.values()))

        # Phase 3: TF × IDF per node + attach to node metadata.
        total_terms = 0
        for node in nodes:
            try:
                tokens = token_lists.get(node.id, [])
                tf = self._compute_tf(tokens)
                vec = self._compute_tfidf(tf, self._idf)
                self._node_vectors[node.id] = vec
                # Mutate metadata in place — the graph still owns the
                # node, this is the standard enrichment pattern.
                if not isinstance(node.metadata, dict):
                    node.metadata = {}
                node.metadata["tfidf_vector"] = vec
                node.metadata["description_text"] = self._node_texts.get(node.id, "")
                total_terms += len(vec)
                report.nodes_enriched += 1
            except Exception as ex:
                report.errors.append(
                    "vector compute failed for " + node.id + ": " + repr(ex)
                )

        report.vocabulary_size = len(self._idf)
        report.avg_vector_length = (
            total_terms / report.nodes_enriched if report.nodes_enriched else 0.0
        )
        return report

    def search(
        self, query_text: str, graph: Any, top_k: int = 10,
    ) -> List[Tuple[str, float]]:
        """Cosine-similarity search against the indexed vectors. The
        `graph` argument is accepted for API symmetry with `enrich()`
        but isn't actually consulted — vectors live on `self`."""
        query_tokens = self._tokenize(query_text or "")
        if not query_tokens:
            return []
        query_tf = self._compute_tf(query_tokens)
        query_vec = self._compute_tfidf(query_tf, self._idf)
        if not query_vec:
            return []
        results: List[Tuple[str, float]] = []
        for node_id, vec in self._node_vectors.items():
            sim = self._cosine_similarity(query_vec, vec)
            if sim > 0.0:
                results.append((node_id, sim))
        results.sort(key=lambda pair: pair[1], reverse=True)
        return results[:top_k]

    # ---- text construction -----------------------------------------

    def _build_node_text(self, node: Any, graph: Any) -> str:
        parts: List[str] = []
        name = node.name or ""
        # Name is repeated three times to give it extra weight relative
        # to docstrings and neighbor names without changing the TF/IDF
        # math.
        parts.append(name)
        parts.append(name)
        parts.append(name)
        if node.type:
            parts.append(node.type)
        if node.docstring:
            parts.append(node.docstring)

        meta = node.metadata or {}
        if node.type == "function":
            for p in meta.get("params", []) or []:
                parts.append(str(p))
        if node.type == "class":
            for b in meta.get("bases", []) or []:
                parts.append(str(b))
        for d in meta.get("decorators", []) or []:
            parts.append(str(d))

        try:
            neighbors = graph.get_neighbors(node.id) or []
        except Exception:
            neighbors = []
        for nb in neighbors:
            if getattr(nb, "name", None):
                parts.append(nb.name)

        return " ".join(parts).lower()

    # ---- tokenization & TF / IDF math ------------------------------

    def _tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        out: List[str] = []
        for tok in _TOKEN_SPLIT_RE.split(text.lower()):
            if len(tok) < 2:
                continue
            if tok in STOP_WORDS:
                continue
            out.append(tok)
        return out

    def _compute_tf(self, tokens: List[str]) -> Dict[str, float]:
        if not tokens:
            return {}
        counts: Dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        total = float(len(tokens))
        return {t: c / total for t, c in counts.items()}

    def _compute_idf(self, all_token_lists: List[List[str]]) -> Dict[str, float]:
        n_docs = len(all_token_lists)
        if n_docs == 0:
            return {}
        doc_freq: Dict[str, int] = {}
        for tokens in all_token_lists:
            for term in set(tokens):
                doc_freq[term] = doc_freq.get(term, 0) + 1
        return {
            term: math.log(n_docs / (1.0 + df))
            for term, df in doc_freq.items()
        }

    def _compute_tfidf(
        self, tf: Dict[str, float], idf: Dict[str, float],
    ) -> Dict[str, float]:
        return {
            term: tf_val * idf.get(term, 0.0)
            for term, tf_val in tf.items()
        }

    def _cosine_similarity(
        self, vec1: Dict[str, float], vec2: Dict[str, float],
    ) -> float:
        if not vec1 or not vec2:
            return 0.0
        # Walk the smaller dict for the dot product so we never iterate
        # more terms than the sparser vector actually has.
        if len(vec1) > len(vec2):
            vec1, vec2 = vec2, vec1
        dot = 0.0
        for term, v in vec1.items():
            other = vec2.get(term)
            if other:
                dot += v * other
        mag1 = math.sqrt(sum(v * v for v in vec1.values()))
        mag2 = math.sqrt(sum(v * v for v in vec2.values()))
        if mag1 == 0.0 or mag2 == 0.0:
            return 0.0
        return dot / (mag1 * mag2)

    # ---- persistence ------------------------------------------------

    def save(self, path: str) -> None:
        payload = {
            "idf": self._idf,
            "node_vectors": self._node_vectors,
            "node_texts": self._node_texts,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    @classmethod
    def load(cls, path: str) -> "TFIDFEnricher":
        """Read a previously-saved index. Spec signature says
        `-> None`, but returning the populated instance is what every
        caller actually needs, so we do that."""
        inst = cls()
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        inst._idf = dict(data.get("idf") or {})
        inst._node_vectors = {
            node_id: dict(vec)
            for node_id, vec in (data.get("node_vectors") or {}).items()
        }
        inst._node_texts = dict(data.get("node_texts") or {})
        return inst


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tfidf_enricher.py <pickle_path> [output_index_path]")
        sys.exit(1)
    with open(sys.argv[1], "rb") as fh:
        graph = pickle.load(fh)
    enricher = TFIDFEnricher()
    report = enricher.enrich(graph)
    print("Enriched " + str(report.nodes_enriched) + " nodes")
    print("Vocabulary size: " + str(report.vocabulary_size))
    print("Avg vector length: {:.1f}".format(report.avg_vector_length))
    if len(sys.argv) > 2:
        enricher.save(sys.argv[2])
        print("Index saved to " + sys.argv[2])
