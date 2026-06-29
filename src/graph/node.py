"""Language-agnostic graph node."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


VALID_NODE_TYPES = frozenset({
    "function",
    "class",
    "module",
    "variable",
    "parameter",
})


@dataclass
class Node:
    """A single entity in the code knowledge graph.

    A `Node` carries no language-specific behaviour; it is a plain
    data record describing one source-level entity (a module, class,
    function, variable, or parameter) discovered by some parser.
    """

    id: str
    name: str
    type: str
    file_path: str
    line_number: int
    language: str
    docstring: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    last_modified: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Node.id must be a non-empty string")
        if self.type not in VALID_NODE_TYPES:
            raise ValueError(
                f"Node.type must be one of {sorted(VALID_NODE_TYPES)}, got {self.type!r}"
            )
        if not isinstance(self.line_number, int):
            raise TypeError("Node.line_number must be an int")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("Node.confidence must be between 0 and 1")
        self.confidence = float(self.confidence)

    @staticmethod
    def make_id(file_path: str, class_name: Optional[str], function_name: Optional[str]) -> str:
        """Build a canonical node id of the form `filepath::classname::functionname`.

        Use empty strings for the segments that do not apply (e.g. for a
        module-level function, pass `class_name=""`).
        """
        return "::".join([file_path or "", class_name or "", function_name or ""])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "language": self.language,
            "docstring": self.docstring,
            "metadata": dict(self.metadata),
            "confidence": self.confidence,
            "last_modified": self.last_modified,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Node":
        return cls(
            id=data["id"],
            name=data["name"],
            type=data["type"],
            file_path=data["file_path"],
            line_number=data["line_number"],
            language=data["language"],
            docstring=data.get("docstring"),
            metadata=dict(data.get("metadata") or {}),
            confidence=float(data.get("confidence", 1.0)),
            last_modified=data.get("last_modified"),
        )

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Node) and self.id == other.id
