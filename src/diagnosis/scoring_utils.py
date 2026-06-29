"""Shared scoring helpers for the diagnosis phase.

`TraversalEngine` (candidate scoring) and `Verifier` (candidate checks)
both reason about git recency and keyword overlap. The mechanics of
those two computations — parsing an ISO commit date into "days ago" and
testing which incident keywords appear in a node's text — are identical
in both places, so they live here and are imported by both.
"""

from datetime import datetime, timezone
from typing import List, Optional


def days_since_iso(date_str: Optional[str]) -> Optional[int]:
    """Whole days between an ISO-8601 timestamp and now (UTC).

    Returns ``None`` when `date_str` is empty or unparseable. Future
    dates are clamped to 0 so a clock skew never yields a negative age.
    """
    if not date_str:
        return None
    try:
        commit_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - commit_date).days)
    except Exception:
        return None


def matched_keywords(keywords: Optional[List[str]], *texts: str) -> List[str]:
    """Return the subset of `keywords` that appear (case-insensitively)
    anywhere in the concatenation of `texts`. Empty/falsy texts are
    ignored. Returns ``[]`` when there are no keywords."""
    if not keywords:
        return []
    haystack = " ".join(t for t in texts if t).lower()
    return [kw for kw in keywords if kw.lower() in haystack]
