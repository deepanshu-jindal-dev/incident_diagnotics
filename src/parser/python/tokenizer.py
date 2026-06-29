"""PythonTokenizer — a from-scratch tokenizer for Python source code.

Implements `BaseTokenizer` without relying on Tree-sitter, the `ast`
module, or any external parsing library. The standard-library `re`
module is used to match the shape of numeric literals and identifiers
but not to drive the overall structure — the main loop is a
hand-written character scanner that owns the indentation stack, the
bracket-nesting counter, and the string-state bookkeeping.
"""

import re
from typing import List, Optional

from ..base_tokenizer import BaseTokenizer, Token


# ----------------------------------------------------------------------
# Token type constants
# ----------------------------------------------------------------------

KEYWORD = "KEYWORD"
IDENTIFIER = "IDENTIFIER"
NUMBER = "NUMBER"
STRING = "STRING"
OPERATOR = "OPERATOR"
DELIMITER = "DELIMITER"
COMMENT = "COMMENT"
NEWLINE = "NEWLINE"
INDENT = "INDENT"
DEDENT = "DEDENT"
ENDMARKER = "ENDMARKER"
ERROR = "ERROR"


# ----------------------------------------------------------------------
# Language tables
# ----------------------------------------------------------------------

PYTHON_KEYWORDS = frozenset({
    "False", "None", "True",
    "and", "as", "assert", "async", "await",
    "break", "class", "continue",
    "def", "del",
    "elif", "else", "except",
    "finally", "for", "from",
    "global",
    "if", "import", "in", "is",
    "lambda",
    "nonlocal", "not",
    "or",
    "pass",
    "raise", "return",
    "try",
    "while", "with",
    "yield",
})

# Valid string-literal prefixes, compared case-insensitively.
STRING_PREFIXES = frozenset({
    "b", "r", "u", "f",
    "br", "rb", "fr", "rf",
})

THREE_CHAR_OPERATORS = frozenset({"**=", "//=", ">>=", "<<="})

TWO_CHAR_OPERATORS = frozenset({
    "**", "//", ">>", "<<",
    "==", "!=", "<=", ">=",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "@=",
    "->", ":=",
})

SINGLE_CHAR_OPERATORS = frozenset("+-*/%@<>&|^~")
SINGLE_CHAR_DELIMITERS = frozenset(",:;.=")
OPEN_BRACKETS = frozenset("([{")
CLOSE_BRACKETS = frozenset(")]}")


# ----------------------------------------------------------------------
# Pre-compiled regexes (shape matching only)
# ----------------------------------------------------------------------

# Hex / oct / bin / decimal int / float / scientific / complex.
# Underscores between digits permitted (PEP 515).
_NUMBER_RE = re.compile(
    r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*"
    r"|0[oO][0-7](?:_?[0-7])*"
    r"|0[bB][01](?:_?[01])*"
    r"|(?:"
        r"(?:\d(?:_?\d)*(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)"
        r"(?:[eE][+-]?\d(?:_?\d)*)?"
        r"[jJ]?"
    r")"
)

# PEP 263 encoding-declaration probe; only meaningful on the first two
# physical lines of a file.
_ENCODING_RE = re.compile(r"coding[:=]\s*([-\w.]+)")


class PythonTokenizer(BaseTokenizer):
    """Tokenizer for Python 3.8+ source text.

    Produces a flat list of `Token` records terminated by a single
    `ENDMARKER`. The tokenizer is re-entrant — calling
    `tokenize(new_source)` resets all internal state.
    """

    # Token-type constants re-exported as class attributes for callers
    # that import the class but not the module.
    KEYWORD = KEYWORD
    IDENTIFIER = IDENTIFIER
    NUMBER = NUMBER
    STRING = STRING
    OPERATOR = OPERATOR
    DELIMITER = DELIMITER
    COMMENT = COMMENT
    NEWLINE = NEWLINE
    INDENT = INDENT
    DEDENT = DEDENT
    ENDMARKER = ENDMARKER
    ERROR = ERROR

    def __init__(self, source: Optional[str] = None) -> None:
        super().__init__(source)
        self._pos: int = 0
        self._line: int = 1
        self._col: int = 0
        self._indent_stack: List[int] = [0]
        self._bracket_depth: int = 0
        self._at_line_start: bool = True

    # --- public API ---------------------------------------------------

    def language(self) -> str:
        return "python"

    def tokenize(self, source: Optional[str] = None) -> List[Token]:
        if source is not None:
            self.reset(source)
        else:
            self.reset(self._source)

        src = self._source
        n = len(src)

        while self._pos < n:
            if self._at_line_start and self._bracket_depth == 0:
                self._handle_indentation()
                if self._pos >= n:
                    break
            self._scan_one_token()

        # End-of-file housekeeping: close any dangling logical line,
        # drain the indentation stack, then emit ENDMARKER.
        if self._tokens and self._tokens[-1].type not in (NEWLINE, INDENT, DEDENT):
            self._emit(NEWLINE, "")
        while len(self._indent_stack) > 1:
            self._indent_stack.pop()
            self._emit(DEDENT, "")
        self._emit(ENDMARKER, "")
        return self._tokens

    def reset(self, source: str) -> None:
        super().reset(source)
        self._pos = 0
        self._line = 1
        self._col = 0
        self._indent_stack = [0]
        self._bracket_depth = 0
        self._at_line_start = True

    # --- main dispatcher ---------------------------------------------

    def _scan_one_token(self) -> None:
        src = self._source
        n = len(src)
        ch = src[self._pos]

        if ch == "\n" or ch == "\r":
            self._handle_newline()
            return

        if ch == " " or ch == "\t":
            self._pos += 1
            self._col += 1
            return

        # Explicit line continuation: a backslash immediately followed
        # by a newline. Swallow both without emitting NEWLINE so the
        # logical line continues onto the next physical line.
        if ch == "\\" and self._pos + 1 < n and src[self._pos + 1] in "\r\n":
            self._pos += 1
            self._col += 1
            if src[self._pos] == "\r":
                self._pos += 1
                if self._pos < n and src[self._pos] == "\n":
                    self._pos += 1
            else:
                self._pos += 1
            self._line += 1
            self._col = 0
            return

        if ch == "#":
            self._tokenize_comment()
            return

        if ch.isdigit():
            self._tokenize_number()
            return

        # `.<digit>` is a float; lone `.` is a delimiter.
        if ch == "." and self._pos + 1 < n and src[self._pos + 1].isdigit():
            self._tokenize_number()
            return

        if ch == '"' or ch == "'":
            self._tokenize_string(prefix="")
            return

        if self._is_identifier_start(ch):
            # Could be a string-literal prefix (`b`, `r`, `f`, `u`,
            # `br`, ...) immediately followed by a quote. Try that first.
            if not self._try_tokenize_prefixed_string():
                self._tokenize_identifier()
            return

        # Operators, delimiters, brackets, or unknown characters.
        self._tokenize_operator_or_delimiter()

    # --- indentation --------------------------------------------------

    def _handle_indentation(self) -> None:
        """Measure leading whitespace on a fresh logical line and emit
        INDENT or DEDENT tokens if the level differs from the top of
        the indent stack. Blank lines and comment-only lines do not
        change the stack and are scanned normally by the main loop.
        """
        src = self._source
        n = len(src)
        p = self._pos

        # Tabs expand to the next multiple of 8; this matches the
        # simplified rule CPython applies when a file mixes tabs and
        # spaces without `-tt`.
        indent = 0
        while p < n and (src[p] == " " or src[p] == "\t"):
            if src[p] == " ":
                indent += 1
            else:
                indent = (indent // 8 + 1) * 8
            p += 1

        # Blank line or comment-only line — leave the stack alone.
        if p >= n or src[p] in ("\n", "\r", "#"):
            self._at_line_start = False
            return

        top = self._indent_stack[-1]
        if indent > top:
            self._indent_stack.append(indent)
            self._emit(INDENT, src[self._pos:p])
        elif indent < top:
            while self._indent_stack and self._indent_stack[-1] > indent:
                self._indent_stack.pop()
                self._emit(DEDENT, "")
            if not self._indent_stack or self._indent_stack[-1] != indent:
                self._emit(ERROR, "inconsistent dedent")
                self._indent_stack.append(indent)

        self._col += p - self._pos
        self._pos = p
        self._at_line_start = False

    def _handle_newline(self) -> None:
        src = self._source
        start_line = self._line
        start_col = self._col
        ch = src[self._pos]
        if ch == "\r":
            self._pos += 1
            if self._pos < len(src) and src[self._pos] == "\n":
                self._pos += 1
        else:
            self._pos += 1
        self._line += 1
        self._col = 0

        # Inside brackets, newlines are implicit continuations.
        if self._bracket_depth > 0:
            return

        self._emit(NEWLINE, "\n", line=start_line, col=start_col)
        self._at_line_start = True

    # --- comments -----------------------------------------------------

    def _tokenize_comment(self) -> None:
        src = self._source
        n = len(src)
        start = self._pos
        start_line = self._line
        start_col = self._col
        p = start
        while p < n and src[p] != "\n" and src[p] != "\r":
            p += 1
        value = src[start:p]
        self._col += p - start
        self._pos = p

        metadata = {}
        if start_line <= 2:
            m = _ENCODING_RE.search(value)
            if m:
                metadata["encoding"] = m.group(1)

        self._emit(COMMENT, value, line=start_line, col=start_col, metadata=metadata)

    # --- numbers ------------------------------------------------------

    def _tokenize_number(self) -> None:
        m = _NUMBER_RE.match(self._source, self._pos)
        if not m:
            # Defensive: should never happen if the dispatcher routed
            # us here, but emit an ERROR instead of crashing.
            self._emit(ERROR, self._source[self._pos])
            self._pos += 1
            self._col += 1
            return
        value = m.group(0)
        self._emit(NUMBER, value, line=self._line, col=self._col)
        consumed = m.end() - m.start()
        self._pos = m.end()
        self._col += consumed

    # --- identifiers & keywords --------------------------------------

    def _tokenize_identifier(self) -> None:
        src = self._source
        n = len(src)
        start = self._pos
        start_line = self._line
        start_col = self._col
        p = start
        while p < n and (src[p].isalnum() or src[p] == "_"):
            p += 1
        name = src[start:p]
        self._pos = p
        self._col += p - start

        token_type = KEYWORD if name in PYTHON_KEYWORDS else IDENTIFIER
        self._emit(token_type, name, line=start_line, col=start_col)

    def _is_identifier_start(self, ch: str) -> bool:
        return ch.isalpha() or ch == "_"

    def _try_tokenize_prefixed_string(self) -> bool:
        """Look for a string-literal prefix followed by an opening quote
        (e.g. ``r"``, ``b'``, or ``fr'''``). Returns True if a string
        token was emitted, False otherwise.
        """
        src = self._source
        n = len(src)
        p = self._pos

        # Read up to two letters of potential prefix.
        prefix_chars = 0
        while prefix_chars < 2 and p + prefix_chars < n and src[p + prefix_chars].isalpha():
            prefix_chars += 1

        for length in (2, 1):
            if length > prefix_chars:
                continue
            if p + length < n and src[p + length] in "\"'":
                prefix = src[p:p + length]
                if prefix.lower() in STRING_PREFIXES:
                    self._pos += length
                    self._col += length
                    self._tokenize_string(prefix=prefix)
                    return True
        return False

    # --- strings ------------------------------------------------------

    def _tokenize_string(self, prefix: str = "") -> None:
        src = self._source
        n = len(src)
        start_line = self._line
        start_col = self._col - len(prefix)
        quote_char = src[self._pos]
        is_triple = (
            self._pos + 2 < n
            and src[self._pos + 1] == quote_char
            and src[self._pos + 2] == quote_char
        )
        is_fstring = "f" in prefix.lower()

        quote_len = 3 if is_triple else 1
        open_quote = src[self._pos:self._pos + quote_len]
        self._pos += quote_len
        self._col += quote_len

        value_chars: List[str] = []
        # Brace nesting inside f-string expressions, so a `"` inside
        # `f"{ 'x' }"` does not prematurely close the outer literal.
        brace_depth = 0

        while self._pos < n:
            ch = src[self._pos]

            # Closing quote? Only when not inside an f-string expression.
            if brace_depth == 0:
                if is_triple:
                    if (
                        ch == quote_char
                        and self._pos + 1 < n and src[self._pos + 1] == quote_char
                        and self._pos + 2 < n and src[self._pos + 2] == quote_char
                    ):
                        self._pos += 3
                        self._col += 3
                        value = prefix + open_quote + "".join(value_chars) + (quote_char * 3)
                        self._emit(STRING, value, line=start_line, col=start_col)
                        return
                else:
                    if ch == quote_char:
                        self._pos += 1
                        self._col += 1
                        value = prefix + open_quote + "".join(value_chars) + quote_char
                        self._emit(STRING, value, line=start_line, col=start_col)
                        return

            # F-string brace bookkeeping (handles `{{` / `}}` escapes
            # and tracks nested expression depth).
            if is_fstring:
                if ch == "{":
                    if brace_depth == 0 and self._pos + 1 < n and src[self._pos + 1] == "{":
                        value_chars.append("{")
                        value_chars.append("{")
                        self._pos += 2
                        self._col += 2
                        continue
                    brace_depth += 1
                    value_chars.append("{")
                    self._pos += 1
                    self._col += 1
                    continue
                if ch == "}":
                    if brace_depth == 0 and self._pos + 1 < n and src[self._pos + 1] == "}":
                        value_chars.append("}")
                        value_chars.append("}")
                        self._pos += 2
                        self._col += 2
                        continue
                    if brace_depth > 0:
                        brace_depth -= 1
                    value_chars.append("}")
                    self._pos += 1
                    self._col += 1
                    continue

            # Newlines inside the string.
            if ch == "\n" or ch == "\r":
                if not is_triple:
                    value = prefix + open_quote + "".join(value_chars)
                    self._emit(
                        ERROR,
                        "unterminated string: " + value,
                        line=start_line,
                        col=start_col,
                    )
                    return
                if ch == "\r":
                    value_chars.append("\n")
                    self._pos += 1
                    if self._pos < n and src[self._pos] == "\n":
                        self._pos += 1
                else:
                    value_chars.append("\n")
                    self._pos += 1
                self._line += 1
                self._col = 0
                continue

            # Backslash: in both raw and non-raw strings, swallow the
            # next character too so `\"` (or `\'`) does not terminate
            # the literal. Whether `\n` decodes to a newline byte is
            # the parser/runtime's concern, not the tokenizer's.
            if ch == "\\" and self._pos + 1 < n:
                next_ch = src[self._pos + 1]
                value_chars.append(ch)
                value_chars.append(next_ch)
                if next_ch == "\r":
                    self._line += 1
                    self._col = 0
                    self._pos += 2
                    if self._pos < n and src[self._pos] == "\n":
                        value_chars.append("\n")
                        self._pos += 1
                elif next_ch == "\n":
                    self._line += 1
                    self._col = 0
                    self._pos += 2
                else:
                    self._pos += 2
                    self._col += 2
                continue

            value_chars.append(ch)
            self._pos += 1
            self._col += 1

        # EOF reached without a closing quote.
        value = prefix + open_quote + "".join(value_chars)
        self._emit(
            ERROR,
            "unterminated string: " + value,
            line=start_line,
            col=start_col,
        )

    # --- operators / delimiters / brackets ---------------------------

    def _tokenize_operator_or_delimiter(self) -> None:
        src = self._source
        n = len(src)
        p = self._pos
        line = self._line
        col = self._col

        # 3-character lookahead (`**=`, `//=`, `>>=`, `<<=`, `...`).
        if p + 2 < n:
            three = src[p:p + 3]
            if three in THREE_CHAR_OPERATORS:
                self._emit(OPERATOR, three, line=line, col=col)
                self._pos += 3
                self._col += 3
                return
            if three == "...":
                self._emit(DELIMITER, "...", line=line, col=col)
                self._pos += 3
                self._col += 3
                return

        # 2-character lookahead (all compound assigns, comparisons, ->, :=).
        if p + 1 < n:
            two = src[p:p + 2]
            if two in TWO_CHAR_OPERATORS:
                self._emit(OPERATOR, two, line=line, col=col)
                self._pos += 2
                self._col += 2
                return

        ch = src[p]

        if ch in OPEN_BRACKETS:
            self._bracket_depth += 1
            self._emit(DELIMITER, ch, line=line, col=col)
            self._pos += 1
            self._col += 1
            return
        if ch in CLOSE_BRACKETS:
            if self._bracket_depth > 0:
                self._bracket_depth -= 1
            self._emit(DELIMITER, ch, line=line, col=col)
            self._pos += 1
            self._col += 1
            return

        if ch in SINGLE_CHAR_OPERATORS:
            self._emit(OPERATOR, ch, line=line, col=col)
            self._pos += 1
            self._col += 1
            return

        if ch in SINGLE_CHAR_DELIMITERS:
            self._emit(DELIMITER, ch, line=line, col=col)
            self._pos += 1
            self._col += 1
            return

        # Unknown character — emit ERROR and advance one step rather
        # than crashing. Tokenization must always make progress.
        self._emit(ERROR, ch, line=line, col=col)
        self._pos += 1
        self._col += 1

    # --- emit helper --------------------------------------------------

    def _emit(
        self,
        token_type: str,
        value: str,
        line: Optional[int] = None,
        col: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self._tokens.append(Token(
            type=token_type,
            value=value,
            line=line if line is not None else self._line,
            column=col if col is not None else self._col,
            metadata=metadata if metadata is not None else {},
        ))
