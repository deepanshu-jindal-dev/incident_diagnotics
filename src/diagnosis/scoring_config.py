"""Scoring signal weights for the traversal engine.

Five signals contribute to a candidate node's final score.
Weights must sum to 1.0.

  proximity    — how close (in hops) the node is to the crash site
  git          — recency of the last commit touching this node
  keyword      — overlap between error keywords and the node name/file
  error_type   — whether the node directly raises the observed exception type
  connectivity — outgoing call-edge count (entry nodes only)
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringWeights:
    proximity:    float = 0.20
    git:          float = 0.35
    keyword:      float = 0.20
    error_type:   float = 0.15
    connectivity: float = 0.10

    def __post_init__(self):
        total = self.proximity + self.git + self.keyword + self.error_type + self.connectivity
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"ScoringWeights must sum to 1.0, got {total:.4f}")


DEFAULT_WEIGHTS = ScoringWeights()
