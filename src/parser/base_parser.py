"""Abstract base class for language parsers."""

from abc import ABC, abstractmethod
from typing import Any, List, Optional

from .base_tokenizer import BaseTokenizer, Token


class BaseParser(ABC):
    """Abstract base class that every language parser must extend.

    A parser consumes a stream of tokens (produced by a `BaseTokenizer`
    subclass) and yields a language-agnostic structured representation
    that downstream components — the knowledge-graph builder in
    particular — can walk.

    Concrete subclasses (e.g. PythonParser, JavaScriptParser) implement
    `parse` from scratch without Tree-sitter, the `ast` module, or any
    external parsing library.
    """

    def __init__(
        self,
        tokenizer: Optional[BaseTokenizer] = None,
        source: Optional[str] = None,
    ) -> None:
        self._tokenizer: Optional[BaseTokenizer] = tokenizer
        self._source: str = source if source is not None else ""
        self._tokens: List[Token] = []
        self._tree: Any = None

    @property
    def tokenizer(self) -> Optional[BaseTokenizer]:
        return self._tokenizer

    @property
    def source(self) -> str:
        return self._source

    @property
    def tokens(self) -> List[Token]:
        return self._tokens

    @property
    def tree(self) -> Any:
        return self._tree

    def reset(self, source: str) -> None:
        """Re-initialise the parser with a new source string."""
        self._source = source
        self._tokens = []
        self._tree = None

    @abstractmethod
    def parse(self, source: Optional[str] = None) -> Any:
        """Parse source code and return a structured representation.
        Implementations should set `self._tree` and return it.
        """
        raise NotImplementedError

    @abstractmethod
    def language(self) -> str:
        """Return the name of the language this parser handles."""
        raise NotImplementedError

    def parse_file(self, path: str, encoding: str = "utf-8") -> Any:
        """Convenience wrapper that reads a file from disk and parses it."""
        with open(path, "r", encoding=encoding) as fh:
            return self.parse(fh.read())
