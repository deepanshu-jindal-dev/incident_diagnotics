"""Language strategy (Strategy pattern) for the ingestion pipeline.

Each language subclass encapsulates its own tokenize → parse → walk
steps using `_FileProcessorBuilder` internally, returning a
`_ProcessResult`. The `LANGUAGE_REGISTRY` maps file extensions to the
strategy that handles them — extend it here to add a new language.
"""

import os
import sys
from abc import ABC, abstractmethod
from typing import Dict

# Make `src/` importable so the parser/graph absolute imports resolve
# regardless of how this module is first imported.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from parser.python.parser import PythonParser  # noqa: E402
from parser.python.tokenizer import PythonTokenizer  # noqa: E402
from parser.python.walker import Walker as PythonWalker  # noqa: E402

from ingestion.file_processor import _FileProcessorBuilder  # noqa: E402
from ingestion.pipeline_reports import _ProcessResult  # noqa: E402


class LanguageStrategy(ABC):
    """Each language subclass encapsulates its own tokenize → parse → walk
    steps using _FileProcessorBuilder internally."""

    @abstractmethod
    def process(self, file_path: str, source: str) -> "_ProcessResult":
        """Build a Graph from *source*, or return a result with graph=None."""
        ...


class PythonStrategy(LanguageStrategy):
    def process(self, file_path: str, source: str) -> "_ProcessResult":
        builder = (
            _FileProcessorBuilder(file_path, source)
            .tokenize(PythonTokenizer)
            .parse(PythonParser)
            .walk(PythonWalker)
        )
        return _ProcessResult(
            graph=builder.build(),
            errors=builder.errors,
            failed_files=builder.failed_files,
        )


LANGUAGE_REGISTRY: Dict[str, LanguageStrategy] = {
    ".py": PythonStrategy(),
}

SUPPORTED_EXTENSIONS = frozenset(LANGUAGE_REGISTRY.keys())
