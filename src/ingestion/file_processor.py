"""Per-file processing builder.

`_FileProcessorBuilder` runs the read → tokenize → parse → walk steps in
order, each returning ``self`` so they can be chained. A failure in any
step sets ``_failed`` and causes all subsequent steps to no-op, so the
chain never needs guard clauses at the call site. The concrete
tokenizer / parser / walker classes are passed in by the caller (the
language strategy), keeping this builder language-agnostic.
"""

import os
import sys
from typing import Any, List, Optional, Type

# Make `src/` importable so `graph.graph.Graph` resolves regardless of
# how this module is first imported.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from graph.graph import Graph  # noqa: E402


class _FileProcessorBuilder:
    """Fluent builder that runs read → tokenize → parse → walk in order.

    Each step returns ``self`` so they can be chained. A failure in any
    step sets ``_failed`` and causes all subsequent steps to no-op, so
    the chain never needs guard clauses at the call site.
    """

    def __init__(self, file_path: str, source: Optional[str] = None) -> None:
        self._file_path = file_path
        self._source: Optional[str] = source
        self._tree: Any = None
        self._per_file_graph: Optional[Graph] = None
        self._failed = False
        self._errors: List[str] = []
        self._failed_files: List[str] = []

    # ---- steps (each returns self) ----------------------------------

    def read(self, reader) -> "_FileProcessorBuilder":
        if self._failed:
            return self
        self._source = reader(self._file_path)
        if self._source is None:
            self._failed = True
            self._failed_files.append(self._file_path)
        return self

    def tokenize(self, tokenizer_cls: Type) -> "_FileProcessorBuilder":
        if self._failed or self._source is None:
            return self
        try:
            tokenizer_cls().tokenize(self._source)
        except Exception as ex:
            self._record_failure("tokenizer: " + repr(ex))
        return self

    def parse(self, parser_cls: Type) -> "_FileProcessorBuilder":
        if self._failed or self._source is None:
            return self
        try:
            parser = parser_cls()
            self._tree = parser.parse(self._source)
            parse_errors = (
                parser.get_errors()
                if callable(getattr(parser, "get_errors", None))
                else []
            )
            if parse_errors:
                sample = ", ".join(
                    "L" + str(e.line) + ": " + e.message
                    for e in parse_errors[:3]
                )
                more = (
                    ""
                    if len(parse_errors) <= 3
                    else " (+" + str(len(parse_errors) - 3) + " more)"
                )
                self._errors.append(
                    self._file_path + ": parser warnings: " + sample + more
                )
        except Exception as ex:
            self._record_failure("parser: " + repr(ex))
        return self

    def walk(self, walker_cls: Type) -> "_FileProcessorBuilder":
        if self._failed or self._tree is None:
            return self
        self._per_file_graph = Graph()
        try:
            walker_cls().walk(self._tree, self._file_path, self._per_file_graph)
        except Exception as ex:
            self._per_file_graph = None
            self._record_failure("walker: " + repr(ex))
        return self

    # ---- terminal ---------------------------------------------------

    def build(self) -> Optional[Graph]:
        """Return the populated per-file graph, or None on any failure."""
        return None if self._failed else self._per_file_graph

    # ---- error plumbing ---------------------------------------------

    @property
    def errors(self) -> List[str]:
        return list(self._errors)

    @property
    def failed_files(self) -> List[str]:
        return list(self._failed_files)

    def _record_failure(self, detail: str) -> None:
        self._failed = True
        self._failed_files.append(self._file_path)
        self._errors.append(self._file_path + ": " + detail)
