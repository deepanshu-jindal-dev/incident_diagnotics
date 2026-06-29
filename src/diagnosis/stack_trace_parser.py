"""Stack trace parser for the Incident Diagnostics Engine.

Accepts any raw text — clean Python tracebacks, log-prefixed output,
chained exceptions, partial/truncated traces, mixed formats — and returns
a structured ParsedIncident. Never crashes on any input.
"""

import os
import re
import sys
from dataclasses import dataclass, field
from typing import List

from diagnosis.frame_parsers import (
    PARSER_REGISTRY,
    StackFrame,
    PY_FRAME_RE as _PY_FRAME_RE,
)
from diagnosis.language_detector import detect_language


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ParsedIncident:
    raw_text: str = ""
    error_type: str = ""
    error_message: str = ""
    frames: List[StackFrame] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    language: str = "python"


# ---------------------------------------------------------------------------
# Noise words removed from keyword extraction
# ---------------------------------------------------------------------------

_GENERIC_WORDS = frozenset({
    # Stack-trace noise
    "traceback", "most", "recent", "call", "last", "file", "line",
    "nonetype", "object", "has", "attribute", "type", "error",
    "exception", "occurred", "during", "handling", "above",
    # Common English function words (stop words for NL queries)
    "the", "in", "at", "of", "to", "for", "and", "or", "not", "is", "it",
    "be", "as", "by", "an", "on", "from", "with", "this", "that", "are",
    "was", "were", "been", "have", "had", "will", "when", "which", "but",
    "if", "then", "into", "how", "what", "where", "any", "their", "they",
    "there", "also", "its", "than", "more", "about", "so", "no", "can",
    "could", "would", "should", "may", "might", "do", "does", "did",
})

# ---------------------------------------------------------------------------
# Pre-compiled patterns
# ---------------------------------------------------------------------------

# Timestamp variants: 2024-01-15 14:30:00,123  /  2024-01-15T14:30:00Z  etc.
_TS_RE = re.compile(
    r"^\d{4}[-/]\d{2}[-/]\d{2}"          # date part
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?"  # optional time
    r"(?:Z|[+-]\d{2}:?\d{2})?)?\s*",     # optional timezone
    re.MULTILINE,
)

# Log level prefixes: ERROR, WARN, WARNING, INFO, DEBUG, TRACE, FATAL,
# optionally bracketed:  [ERROR]  (INFO)  |WARN|
_LEVEL_RE = re.compile(
    r"^\s*[\[\(|]?"
    r"(?:ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL|CRITICAL|SEVERE)"
    r"[\]\)|]?\s*:?\s*",
    re.MULTILINE | re.IGNORECASE,
)

# Thread/logger-name prefix common in Java-style frameworks bleeding into
# Python logs:  [main]  [pool-1-thread-2]  [my.logger.name]
_BRACKET_PREFIX_RE = re.compile(r"^\s*\[[^\]]{1,60}\]\s*", re.MULTILINE)

# Error-type: word(s) ending in Error or Exception optionally followed by ":"
_ERROR_TYPE_RE = re.compile(
    r"(?:^|\s)"                          # start of line or whitespace
    r"((?:\w+\.)*\w*(?:Error|Exception|Warning|Fault|Panic))"
    r"\s*:",
    re.MULTILINE,
)

# Fully-qualified exception from a known exceptions module:
#   werkzeug.exceptions.NotFound:
#   jinja2.exceptions.TemplateNotFound:
# Captures the final CapitalizedWord regardless of suffix.
_EXCEPTIONS_MODULE_RE = re.compile(
    r"(?:^|\s)((?:\w+\.)*exceptions\.([A-Z]\w+))\s*:",
    re.MULTILINE,
)

# Fallback: anything that looks like AnIdentifier: at the start of a line
_ERROR_TYPE_FALLBACK_RE = re.compile(
    r"^([A-Z]\w+(?:\.\w+)*)\s*:",
    re.MULTILINE,
)

# Word tokenizer for keyword extraction
_WORD_RE = re.compile(r"[a-zA-Z_]\w*")

# Camel-case splitter: "NoneType" → ["None", "Type"], "ValueError" → ["Value", "Error"]
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|[0-9]+")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class StackTraceParser:
    """Parse raw incident text into a structured ParsedIncident."""

    def parse(self, raw_text: str) -> ParsedIncident:
        try:
            return self._parse_internal(raw_text or "")
        except Exception:
            # Absolute last resort — never let any exception escape.
            incident = ParsedIncident()
            incident.raw_text = raw_text or ""
            return incident

    def _parse_internal(self, raw_text: str) -> ParsedIncident:
        incident = ParsedIncident()
        incident.raw_text = raw_text

        cleaned = self._preprocess(raw_text)
        incident.language = self._detect_language(cleaned)

        parser = PARSER_REGISTRY.get(incident.language, PARSER_REGISTRY["unknown"])
        incident.frames = parser.extract_frames(cleaned)

        incident.error_type = self._extract_error_type(cleaned)
        incident.error_message = self._extract_error_message(
            cleaned, incident.error_type
        )
        incident.keywords = self._extract_keywords(
            cleaned, incident.error_type, incident.error_message, incident.frames
        )
        return incident

    # -----------------------------------------------------------------------
    # Pre-processing
    # -----------------------------------------------------------------------

    def _preprocess(self, text: str) -> str:
        # Normalise Windows line endings first.
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        lines = text.split("\n")
        cleaned: List[str] = []
        for line in lines:
            line = self._strip_log_prefix(line)
            cleaned.append(line)
        return "\n".join(cleaned)

    def _strip_log_prefix(self, line: str) -> str:
        # 1. Timestamp
        line = _TS_RE.sub("", line, count=1)
        # 2. Log level (may appear after timestamp removal)
        line = _LEVEL_RE.sub("", line, count=1)
        # 3. Bracketed thread/logger name that sometimes follows the level
        #    but only when nothing meaningful has been consumed yet on
        #    this pass (keeps "[ERROR]" logic from eating frame brackets).
        line = _BRACKET_PREFIX_RE.sub("", line, count=1)
        return line

    # -----------------------------------------------------------------------
    # Error type / message
    # -----------------------------------------------------------------------

    def _extract_error_type(self, text: str) -> str:
        # Highest priority: fully-qualified *.exceptions.SomeName: form.
        # Catches NotFound, MethodNotAllowed, TemplateNotFound etc. which
        # don't end in Error/Exception but are unambiguously exceptions.
        for m in _EXCEPTIONS_MODULE_RE.finditer(text):
            if m.group(2):
                return m.group(2)

        # Prefer the canonical XxxError: / XxxException: form.
        for m in _ERROR_TYPE_RE.finditer(text):
            candidate = m.group(1)
            if candidate:
                # Return the last component if fully-qualified (a.b.ValueError).
                return candidate.split(".")[-1]

        # Fallback: first CapitalizedWord: at line start that isn't a
        # known Python keyword or a frame header keyword.
        _frame_starts = {"File", "Traceback", "During", "The"}
        for m in _ERROR_TYPE_FALLBACK_RE.finditer(text):
            candidate = m.group(1)
            if candidate not in _frame_starts:
                return candidate.split(".")[-1]

        return ""

    def _extract_error_message(self, text: str, error_type: str) -> str:
        if not error_type:
            return ""

        lines = text.split("\n")
        message_lines: List[str] = []
        found = False

        for i, line in enumerate(lines):
            if not found:
                # Find the line that contains "ErrorType: ..."
                idx = line.find(error_type + ":")
                if idx == -1:
                    continue
                after_colon = line[idx + len(error_type) + 1:].strip()
                if after_colon:
                    message_lines.append(after_colon)
                found = True
                continue

            # Collect continuation lines for multiline error messages.
            # Stop at blank lines or lines that start a new traceback section.
            stripped = line.strip()
            if not stripped:
                break
            # A new frame or a new error type signals the end.
            if _PY_FRAME_RE.match(line) or _ERROR_TYPE_RE.search(line):
                break
            # Accept indented lines AND lines that begin with characters
            # typical of unindented continuations: list markers, quotes,
            # path separators. Bare alphabetic starts at column 0 that
            # look like new statements are still rejected.
            first = line[0] if line else ""
            is_indented = first in (" ", "\t")
            is_continuation_char = first in ("-", "*", "+", "'", '"', "/", "\\", "[", "{", "(")
            if is_indented or is_continuation_char:
                message_lines.append(stripped)
            else:
                break

        return " ".join(message_lines).strip()

    # -----------------------------------------------------------------------
    # Keyword extraction
    # -----------------------------------------------------------------------

    def _extract_keywords(
        self,
        text: str,
        error_type: str,
        error_message: str,
        frames: List[StackFrame],
    ) -> List[str]:
        seen: dict = {}  # preserves insertion order, deduplicates

        def add(word: str) -> None:
            w = word.lower().strip("_")
            if (
                len(w) <= 1
                or w in _GENERIC_WORDS
                or w.isdigit()
            ):
                return
            seen[w] = None

        # Words from error type (split on dots and camel-case boundaries).
        if error_type:
            # Split camel-case: ValueError → value, error (but "error" is
            # filtered by _GENERIC_WORDS; "value" survives).
            for part in re.split(r"[._]", error_type):
                for sub in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", part):
                    add(sub)

        # Words from error message — with camel-case splitting so that
        # tokens like "NoneType" decompose into "none" + "type" rather
        # than being swallowed whole by the "nonetype" entry in _GENERIC_WORDS.
        for word in _WORD_RE.findall(error_message):
            parts = _CAMEL_RE.findall(word)
            if len(parts) > 1:
                for part in parts:
                    add(part)
            else:
                add(word)

        # Function names from frames.
        for frame in frames:
            if frame.function_name and frame.function_name not in ("<module>", "?"):
                for part in re.split(r"[._]", frame.function_name):
                    add(part)

        # File names from frames (without extension).
        for frame in frames:
            if frame.file_path:
                basename = os.path.basename(frame.file_path)
                stem = os.path.splitext(basename)[0]
                if stem not in ("<string>", "<stdin>", "<module>"):
                    add(stem)

        # Free-text fallback: when there are no frames and no error type the
        # input is a natural language query. Extract content words from the
        # raw text so TF-IDF has something to search with.
        if not frames and not error_type:
            for word in _WORD_RE.findall(text):
                parts = _CAMEL_RE.findall(word)
                if len(parts) > 1:
                    for part in parts:
                        add(part)
                else:
                    add(word)

        return list(seen.keys())

    # -----------------------------------------------------------------------
    # Language detection
    # -----------------------------------------------------------------------

    def _detect_language(self, text: str) -> str:
        return detect_language(text)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        raw = sys.stdin.read()
    else:
        with open(sys.argv[1]) as f:
            raw = f.read()

    parser = StackTraceParser()
    incident = parser.parse(raw)

    print(f"Language:      {incident.language}")
    print(f"Error type:    {incident.error_type}")
    print(f"Error message: {incident.error_message}")
    print(f"Frames:        {len(incident.frames)}")
    for frame in incident.frames:
        print(f"  {frame.file_path}:{frame.line_number} in {frame.function_name}")
    print(f"Keywords:      {incident.keywords}")
