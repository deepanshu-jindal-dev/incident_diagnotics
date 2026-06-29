"""Language-agnostic graph edge."""

from dataclasses import dataclass, field
from typing import Any, Dict


VALID_RELATIONSHIPS = frozenset({
    "CALLS",
    "IMPORTS",
    "EXTENDS",
    "IMPLEMENTS",
    "INSTANTIATES",
    "DECORATES",
    "CONTAINS",
    "RAISES",
    "CATCHES",
})


@dataclass
class Edge:
    """A directed relationship between two nodes in the knowledge graph.

    The `source_id` and `target_id` are the `Node.id` strings of the
    endpoints. The edge itself stores no language-specific data — the
    `relationship` field is a free-form string drawn from a fixed
    vocabulary that any language can map onto.
    """

    id: str
    source_id: str
    target_id: str
    relationship: str
    confidence: float = 1.0
    is_resolved: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Edge.id must be a non-empty string")
        if not isinstance(self.source_id, str) or not self.source_id:
            raise ValueError("Edge.source_id must be a non-empty string")
        if not isinstance(self.target_id, str) or not self.target_id:
            raise ValueError("Edge.target_id must be a non-empty string")
        if self.relationship not in VALID_RELATIONSHIPS:
            raise ValueError(
                f"Edge.relationship must be one of {sorted(VALID_RELATIONSHIPS)}, "
                f"got {self.relationship!r}"
            )
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("Edge.confidence must be between 0 and 1")
        self.confidence = float(self.confidence)
        self.is_resolved = bool(self.is_resolved)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship": self.relationship,
            "confidence": self.confidence,
            "is_resolved": self.is_resolved,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Edge":
        return cls(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            relationship=data["relationship"],
            confidence=float(data.get("confidence", 1.0)),
            is_resolved=bool(data.get("is_resolved", False)),
            metadata=dict(data.get("metadata") or {}),
        )

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Edge) and self.id == other.id
