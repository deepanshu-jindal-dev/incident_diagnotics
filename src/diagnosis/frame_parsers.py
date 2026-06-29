"""Stack-frame extraction — the StackFrame record + per-language parser
strategies.

This module owns everything to do with turning raw trace text into a
list of `StackFrame`s: the frame-matching regexes, the two module-level
extractors (`_extract_python_frames` / `_extract_generic_frames`), and
the Strategy classes registered in `PARSER_REGISTRY`. The higher-level
`StackTraceParser` consumes `PARSER_REGISTRY` to pull frames out of a
trace; it also reuses `PY_FRAME_RE` when deciding where an error message
ends.

Kept separate from `stack_trace_parser` so the parsing-strategy
machinery and the frame record live in one place, and so importing
`StackFrame` never drags in the whole parser.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


# ---------------------------------------------------------------------------
# Frame record
# ---------------------------------------------------------------------------

@dataclass
class StackFrame:
    file_path: str = ""
    function_name: str = ""
    line_number: int = 0
    code_context: str = ""


# ---------------------------------------------------------------------------
# Frame-matching patterns
# ---------------------------------------------------------------------------

# Standard Python frame:   File "path", line N, in func_name
PY_FRAME_RE = re.compile(
    r'^\s*File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+(\S+))?',
    re.MULTILINE,
)

# Optional code-context line directly following a frame header — any line
# that is indented and NOT another frame header or error line.
PY_CODE_CTX_RE = re.compile(r"^    (.+)$", re.MULTILINE)

# Generic frame patterns — tried in order, first match wins per line.
GENERIC_PATTERNS = [
    # at place_order (order.py:42)  — JS/Java style leaking into mixed logs
    re.compile(
        r"^\s*at\s+(\S+)\s+\(([^)]+):(\d+)(?::\d+)?\)",
        re.MULTILINE,
    ),
    # order.py:42 in place_order
    re.compile(
        r"^\s*([^\s:]+\.(?:py|js|ts|java|rb|go|cs|cpp|c|php|rs))"
        r":(\d+)\s+in\s+(\S+)",
        re.MULTILINE,
    ),
    # order.py:42  (bare, no function)
    re.compile(
        r"^\s*([^\s:]+\.(?:py|js|ts|java|rb|go|cs|cpp|c|php|rs)):(\d+)",
        re.MULTILINE,
    ),
    # ERROR order.py:42 place_order failed
    re.compile(
        r"(?:ERROR|WARN|INFO|DEBUG)\s+"
        r"([^\s:]+\.(?:py|js|ts|java|rb|go|cs|cpp|c|php|rs))"
        r":(\d+)\s+(\S+)",
        re.MULTILINE | re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# Parser strategies
# ---------------------------------------------------------------------------

class _StackTraceParserStrategy(ABC):
    """Each language subclass knows how to extract frames from its own
    stack trace format."""

    @abstractmethod
    def extract_frames(self, text: str) -> List[StackFrame]:
        ...


class _PythonStackTraceParser(_StackTraceParserStrategy):
    def extract_frames(self, text: str) -> List[StackFrame]:
        frames = _extract_python_frames(text)
        if not frames:
            frames = _extract_generic_frames(text)
        return frames


class _UnknownStackTraceParser(_StackTraceParserStrategy):
    """Fallback for languages not yet implemented — best-effort generic match."""
    def extract_frames(self, text: str) -> List[StackFrame]:
        return _extract_generic_frames(text)


PARSER_REGISTRY: dict = {
    "python":     _PythonStackTraceParser(),
    "javascript": _UnknownStackTraceParser(),  # not yet implemented
    "java":       _UnknownStackTraceParser(),  # not yet implemented
    "go":         _UnknownStackTraceParser(),  # not yet implemented
    "ruby":       _UnknownStackTraceParser(),  # not yet implemented
    "unknown":    _UnknownStackTraceParser(),
}


# ---------------------------------------------------------------------------
# Module-level frame extractors (used by strategies above)
# ---------------------------------------------------------------------------

def _extract_python_frames(text: str) -> List[StackFrame]:
    frames: List[StackFrame] = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = PY_FRAME_RE.match(lines[i])
        if m:
            frame = StackFrame(
                file_path=m.group(1),
                line_number=int(m.group(2)),
                function_name=m.group(3) or "",
            )
            if i + 1 < len(lines):
                ctx_m = PY_CODE_CTX_RE.match(lines[i + 1])
                if ctx_m and not PY_FRAME_RE.match(lines[i + 1]):
                    frame.code_context = ctx_m.group(1).strip()
                    i += 1
            frames.append(frame)
        i += 1
    return frames


def _extract_generic_frames(text: str) -> List[StackFrame]:
    frames_with_pos: List[tuple] = []
    seen_spans: List[tuple] = []

    for pattern in GENERIC_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if any(s < end and start < e for s, e in seen_spans):
                continue
            seen_spans.append((start, end))

            groups = m.groups()
            frame = StackFrame()

            if len(groups) == 3:
                g0, g1, g2 = groups
                if g1 and g1.isdigit():
                    frame.file_path = g0 or ""
                    frame.line_number = int(g1)
                    frame.function_name = g2 or ""
                else:
                    frame.function_name = g0 or ""
                    frame.file_path = g1 or ""
                    frame.line_number = int(g2) if (g2 and g2.isdigit()) else 0
            elif len(groups) == 2:
                frame.file_path = groups[0] or ""
                frame.line_number = int(groups[1]) if groups[1].isdigit() else 0

            if frame.file_path or frame.line_number:
                frames_with_pos.append((start, frame))

    frames_with_pos.sort(key=lambda t: t[0])

    seen_keys: set = set()
    frames: List[StackFrame] = []
    for _, frame in frames_with_pos:
        key = (frame.file_path, frame.line_number, frame.function_name)
        if key not in seen_keys:
            seen_keys.add(key)
            frames.append(frame)
    return frames
