"""Abstract base class for language tokenizers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable, Iterator, List, Optional


@dataclass
class Token:
    """A single lexical token produced by a tokenizer.

    Fields are intentionally generic so they can describe tokens from
    any language (Python, JavaScript, Java, ...).
    """

    type: str
    value: str
    line: int = 0
    column: int = 0
    metadata: dict = field(default_factory=dict)


class BaseTokenizer(ABC):
    """Abstract base class that every language tokenizer must extend.

    Concrete subclasses (e.g. PythonTokenizer, JavaScriptTokenizer)
    are responsible for turning raw source code into a stream of
    `Token` objects without using Tree-sitter, the `ast` module, or
    any external parsing library.
    """

    def __init__(self, source: Optional[str] = None) -> None:
        self._source: str = source if source is not None else ""
        self._tokens: List[Token] = []

    @property
    def source(self) -> str:
        return self._source

    @property
    def tokens(self) -> List[Token]:
        return self._tokens

    def reset(self, source: str) -> None:
        """Re-initialise the tokenizer with a new source string."""
        self._source = source
        self._tokens = []

    @abstractmethod
    def tokenize(self, source: Optional[str] = None) -> List[Token]:
        """Convert source code into a list of tokens.

        Implementations must populate and return `self._tokens`.
        """
        raise NotImplementedError

    @abstractmethod
    def language(self) -> str:
        """Return the name of the language this tokenizer handles."""
        raise NotImplementedError

    def __iter__(self) -> Iterator[Token]:
        return iter(self._tokens)

    def __len__(self) -> int:
        return len(self._tokens)

    def extend(self, tokens: Iterable[Token]) -> None:
        """Append already-built tokens to the internal buffer."""
        self._tokens.extend(tokens)
