"""PythonParser — recursive-descent parser for Python 3.8+ source code.

Consumes the token stream produced by `PythonTokenizer` and produces a
tree of small AST node records. Expression parsing uses precedence
climbing; statement parsing dispatches on the first token. Errors are
collected on the parser instance (`get_errors()`) and the parser tries
to recover by skipping to the next statement boundary so one bad
construct does not lose the rest of the file.
"""

from typing import Any, Dict, List, Optional, Tuple as Tup

from ..base_parser import BaseParser
from ..base_tokenizer import Token
from .tokenizer import (
    PythonTokenizer,
    KEYWORD, IDENTIFIER, NUMBER, STRING, OPERATOR, DELIMITER,
    COMMENT, NEWLINE, INDENT, DEDENT, ENDMARKER, ERROR,
)


# ======================================================================
# AST node classes
# ======================================================================
# Defined in ast_nodes.py and imported wholesale: the parser constructs
# every node type below, so the full node namespace is brought in here.

from .ast_nodes import *  # noqa: F401,F403


# ======================================================================
# Token stream helper
# ======================================================================


class _TokenStream:
    """Thin cursor over a token list. Drops COMMENT tokens up-front so
    grammar rules never have to skip them. Always returns the trailing
    ENDMARKER when the cursor walks off the end."""

    def __init__(self, tokens: List[Token]) -> None:
        self._tokens = [t for t in tokens if t.type != COMMENT]
        if not self._tokens or self._tokens[-1].type != ENDMARKER:
            tail_line = self._tokens[-1].line if self._tokens else 1
            self._tokens.append(Token(type=ENDMARKER, value="", line=tail_line, column=0))
        self._pos = 0

    def peek(self, offset: int = 0) -> Token:
        idx = self._pos + offset
        if idx >= len(self._tokens):
            return self._tokens[-1]
        return self._tokens[idx]

    def advance(self) -> Token:
        tok = self._tokens[self._pos]
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return tok

    def at_end(self) -> bool:
        return self.peek().type == ENDMARKER

    def save(self) -> int:
        return self._pos

    def restore(self, pos: int) -> None:
        self._pos = pos


# ======================================================================
# Parser
# ======================================================================


_AUG_OPS = frozenset({
    "+=", "-=", "*=", "/=", "//=", "**=", "%=", "@=",
    "&=", "|=", "^=", ">>=", "<<=",
})


class PythonParser(BaseParser):
    """Recursive-descent parser for Python 3.8+."""

    def __init__(self, source: Optional[str] = None) -> None:
        super().__init__(source=source)
        self._stream: Optional[_TokenStream] = None
        self._errors: List[ParseError] = []

    # ---- public API --------------------------------------------------

    def language(self) -> str:
        return "python"

    def get_errors(self) -> List[ParseError]:
        return list(self._errors)

    def parse(self, source: Optional[str] = None) -> Module:
        if source is not None:
            self.reset(source)
        self._errors = []
        tokenizer = PythonTokenizer()
        self._tokens = tokenizer.tokenize(self._source)
        self._stream = _TokenStream(self._tokens)
        self._tree = self._parse_module()
        return self._tree

    # ---- low-level token helpers ------------------------------------

    def _peek(self, offset: int = 0) -> Token:
        return self._stream.peek(offset)

    def _advance(self) -> Token:
        return self._stream.advance()

    def _at_end(self) -> bool:
        return self._stream.at_end()

    def _check(self, tok_type: str, value: Optional[str] = None) -> bool:
        tok = self._peek()
        if tok.type != tok_type:
            return False
        return value is None or tok.value == value

    def _check_kw(self, kw: str) -> bool:
        return self._check(KEYWORD, kw)

    def _check_op(self, op: str) -> bool:
        return self._check(OPERATOR, op)

    def _check_delim(self, d: str) -> bool:
        return self._check(DELIMITER, d)

    def _match(self, tok_type: str, value: Optional[str] = None) -> Optional[Token]:
        if self._check(tok_type, value):
            return self._advance()
        return None

    def _match_kw(self, kw: str) -> Optional[Token]:
        return self._match(KEYWORD, kw)

    def _match_op(self, op: str) -> Optional[Token]:
        return self._match(OPERATOR, op)

    def _match_delim(self, d: str) -> Optional[Token]:
        return self._match(DELIMITER, d)

    def _expect(self, tok_type: str, value: Optional[str] = None) -> Token:
        if self._check(tok_type, value):
            return self._advance()
        tok = self._peek()
        descr = tok_type + ((" " + repr(value)) if value is not None else "")
        self._error("expected " + descr + ", got " + tok.type + " " + repr(tok.value))
        return tok

    def _expect_kw(self, kw: str) -> Token:
        return self._expect(KEYWORD, kw)

    def _expect_delim(self, d: str) -> Token:
        return self._expect(DELIMITER, d)

    def _error(self, msg: str, line: Optional[int] = None) -> None:
        tok = self._peek()
        self._errors.append(ParseError(
            message=msg,
            line=line if line is not None else tok.line,
            column=tok.column,
        ))

    def _error_node(self, msg: str) -> ErrorNode:
        tok = self._peek()
        self._error(msg)
        return ErrorNode(message=msg, line=tok.line)

    def _skip_to_next_statement(self) -> None:
        depth = 0
        while not self._at_end():
            tok = self._peek()
            if tok.type == DELIMITER and tok.value in "([{":
                depth += 1
            elif tok.type == DELIMITER and tok.value in ")]}":
                if depth == 0:
                    return
                depth -= 1
            elif tok.type == NEWLINE and depth == 0:
                self._advance()
                return
            elif tok.type == DEDENT:
                return
            self._advance()

    def _consume_newline(self) -> None:
        if self._check(NEWLINE):
            self._advance()
        elif self._check_delim(";"):
            self._advance()

    # ---- module / block / suite -------------------------------------

    def _parse_module(self) -> Module:
        body: List[Any] = []
        first_line = self._peek().line
        while not self._at_end():
            if self._check(NEWLINE) or self._check(INDENT) or self._check(DEDENT):
                self._advance()
                continue
            try:
                stmt = self._parse_statement()
            except _RecoveryAbort:
                self._skip_to_next_statement()
                continue
            if stmt is None:
                continue
            if isinstance(stmt, list):
                body.extend(stmt)
            else:
                body.append(stmt)
        return Module(body=body, line=first_line)

    def _parse_block(self) -> List[Any]:
        """Parse an indented block following an opening colon+NEWLINE."""
        stmts: List[Any] = []
        # Comments and blank lines may appear before the INDENT token.
        # Skip them so the INDENT check below finds the real block opener.
        while self._check(COMMENT) or self._check(NEWLINE):
            self._advance()
        if not self._match(INDENT):
            # Single-line suite: stmt; stmt; ... NEWLINE
            return self._parse_simple_suite()
        while not self._check(DEDENT) and not self._at_end():
            if self._check(NEWLINE) or self._check(COMMENT):
                self._advance()
                continue
            try:
                stmt = self._parse_statement()
            except _RecoveryAbort:
                self._skip_to_next_statement()
                continue
            if stmt is None:
                continue
            if isinstance(stmt, list):
                stmts.extend(stmt)
            else:
                stmts.append(stmt)
        self._match(DEDENT)
        return stmts

    def _parse_suite(self) -> List[Any]:
        if self._check(NEWLINE):
            self._advance()
            return self._parse_block()
        return self._parse_simple_suite()

    def _parse_simple_suite(self) -> List[Any]:
        stmts: List[Any] = []
        while True:
            if self._check(NEWLINE) or self._at_end():
                if self._check(NEWLINE):
                    self._advance()
                break
            stmt = self._parse_statement()
            if stmt is not None:
                if isinstance(stmt, list):
                    stmts.extend(stmt)
                else:
                    stmts.append(stmt)
            if self._check_delim(";"):
                self._advance()
                continue
            break
        return stmts

    # ---- statement dispatch -----------------------------------------

    def _parse_statement(self) -> Any:
        tok = self._peek()

        if tok.type == KEYWORD:
            kw = tok.value
            if kw == "def":
                return self._parse_function_def(is_async=False)
            if kw == "async":
                return self._parse_async_statement()
            if kw == "class":
                return self._parse_class_def()
            if kw == "if":
                return self._parse_if_stmt()
            if kw == "while":
                return self._parse_while_stmt()
            if kw == "for":
                return self._parse_for_stmt(is_async=False)
            if kw == "try":
                return self._parse_try_stmt()
            if kw == "with":
                return self._parse_with_stmt(is_async=False)
            if kw == "return":
                return self._parse_return_stmt()
            if kw == "raise":
                return self._parse_raise_stmt()
            if kw == "import":
                return self._parse_import_stmt()
            if kw == "from":
                return self._parse_from_stmt()
            if kw == "global":
                return self._parse_global_stmt()
            if kw == "nonlocal":
                return self._parse_nonlocal_stmt()
            if kw == "del":
                return self._parse_del_stmt()
            if kw == "assert":
                return self._parse_assert_stmt()
            if kw == "yield":
                return self._parse_yield_stmt()
            if kw == "pass":
                line = tok.line
                self._advance()
                stmt = PassStatement(line=line)
                self._consume_newline()
                return stmt
            if kw == "break":
                line = tok.line
                self._advance()
                stmt = BreakStatement(line=line)
                self._consume_newline()
                return stmt
            if kw == "continue":
                line = tok.line
                self._advance()
                stmt = ContinueStatement(line=line)
                self._consume_newline()
                return stmt

        if tok.type == OPERATOR and tok.value == "@":
            return self._parse_decorated()

        if self._looks_like_match():
            return self._parse_match_stmt()

        return self._parse_expr_or_assign_stmt()

    # ---- compound statements ----------------------------------------

    def _parse_function_def(self, is_async: bool = False,
                            decorators: Optional[List[Any]] = None) -> Any:
        line = self._peek().line
        self._expect_kw("def")
        name_tok = self._expect(IDENTIFIER)
        self._expect_delim("(")
        params = self._parse_parameters()
        self._expect_delim(")")
        returns: Optional[Any] = None
        if self._match_op("->"):
            returns = self._parse_expression()
        self._expect_delim(":")
        body = self._parse_suite()
        decs = decorators or []
        if is_async:
            return AsyncFunctionDef(
                name=name_tok.value, params=params, body=body,
                decorators=decs, returns=returns, line=line,
            )
        return FunctionDef(
            name=name_tok.value, params=params, body=body,
            decorators=decs, returns=returns, line=line,
        )

    def _parse_async_statement(self) -> Any:
        self._advance()  # 'async'
        if self._check_kw("def"):
            return self._parse_function_def(is_async=True)
        if self._check_kw("for"):
            return self._parse_for_stmt(is_async=True)
        if self._check_kw("with"):
            return self._parse_with_stmt(is_async=True)
        self._error("expected 'def', 'for', or 'with' after 'async'")
        self._skip_to_next_statement()
        return None

    def _parse_class_def(self, decorators: Optional[List[Any]] = None) -> ClassDef:
        line = self._peek().line
        self._expect_kw("class")
        name_tok = self._expect(IDENTIFIER)
        bases: List[Any] = []
        keywords: List[Any] = []
        if self._match_delim("("):
            if not self._check_delim(")"):
                bases, keywords = self._parse_call_arguments_split()
            self._expect_delim(")")
        self._expect_delim(":")
        body = self._parse_suite()
        return ClassDef(
            name=name_tok.value, bases=bases, keywords=keywords,
            body=body, decorators=decorators or [], line=line,
        )

    def _parse_call_arguments_split(self) -> Tup[List[Argument], List[Argument]]:
        positional: List[Argument] = []
        keywords: List[Argument] = []
        while not self._check_delim(")"):
            arg = self._parse_argument()
            if arg.name is not None and not arg.is_double_star:
                keywords.append(arg)
            else:
                positional.append(arg)
            if not self._match_delim(","):
                break
        return positional, keywords

    def _parse_if_stmt(self) -> IfStatement:
        return self._parse_if_or_elif("if")

    def _parse_elif_clause(self) -> IfStatement:
        return self._parse_if_or_elif("elif")

    def _parse_if_or_elif(self, keyword: str) -> IfStatement:
        """Parse an `if` or `elif` header and its suite. A trailing
        `elif` recurses (nested in `orelse`); a trailing `else` becomes
        the `orelse` suite directly. The two entry points differ only in
        the opening keyword they expect."""
        line = self._peek().line
        self._expect_kw(keyword)
        test = self._parse_expression()
        self._expect_delim(":")
        body = self._parse_suite()
        orelse: List[Any] = []
        if self._check_kw("elif"):
            orelse = [self._parse_elif_clause()]
        elif self._match_kw("else"):
            self._expect_delim(":")
            orelse = self._parse_suite()
        return IfStatement(test=test, body=body, orelse=orelse, line=line)

    def _parse_while_stmt(self) -> WhileLoop:
        line = self._peek().line
        self._expect_kw("while")
        test = self._parse_expression()
        self._expect_delim(":")
        body = self._parse_suite()
        orelse: List[Any] = []
        if self._match_kw("else"):
            self._expect_delim(":")
            orelse = self._parse_suite()
        return WhileLoop(test=test, body=body, orelse=orelse, line=line)

    def _parse_for_stmt(self, is_async: bool = False) -> ForLoop:
        line = self._peek().line
        self._expect_kw("for")
        target = self._parse_target_list()
        self._expect_kw("in")
        iter_expr = self._parse_expression_list()
        self._expect_delim(":")
        body = self._parse_suite()
        orelse: List[Any] = []
        if self._match_kw("else"):
            self._expect_delim(":")
            orelse = self._parse_suite()
        return ForLoop(
            target=target, iter=iter_expr, body=body, orelse=orelse,
            is_async=is_async, line=line,
        )

    def _parse_try_stmt(self) -> TryStatement:
        line = self._peek().line
        self._expect_kw("try")
        self._expect_delim(":")
        body = self._parse_suite()
        handlers: List[ExceptHandler] = []
        orelse: List[Any] = []
        finalbody: List[Any] = []
        while self._check_kw("except"):
            handlers.append(self._parse_except_handler())
        if self._match_kw("else"):
            self._expect_delim(":")
            orelse = self._parse_suite()
        if self._match_kw("finally"):
            self._expect_delim(":")
            finalbody = self._parse_suite()
        return TryStatement(
            body=body, handlers=handlers, orelse=orelse,
            finalbody=finalbody, line=line,
        )

    def _parse_except_handler(self) -> ExceptHandler:
        line = self._peek().line
        self._expect_kw("except")
        # `except*` for 3.11 exception groups — accept and ignore the star
        self._match_op("*")
        exc_type: Optional[Any] = None
        name: Optional[str] = None
        if not self._check_delim(":"):
            exc_type = self._parse_expression()
            if self._match_kw("as"):
                name = self._expect(IDENTIFIER).value
        self._expect_delim(":")
        body = self._parse_suite()
        return ExceptHandler(type=exc_type, name=name, body=body, line=line)

    def _parse_with_stmt(self, is_async: bool = False) -> WithStatement:
        line = self._peek().line
        self._expect_kw("with")
        items: List[Tup[Any, Any]] = []
        has_paren = self._match_delim("(") is not None
        items.append(self._parse_with_item())
        while self._match_delim(","):
            if has_paren and self._check_delim(")"):
                break
            items.append(self._parse_with_item())
        if has_paren:
            self._expect_delim(")")
        self._expect_delim(":")
        body = self._parse_suite()
        return WithStatement(items=items, body=body, is_async=is_async, line=line)

    def _parse_with_item(self) -> Tup[Any, Any]:
        expr = self._parse_expression()
        target = None
        if self._match_kw("as"):
            target = self._parse_target()
        return (expr, target)

    def _parse_decorated(self) -> Any:
        decorators: List[Decorator] = []
        while self._check_op("@"):
            line = self._peek().line
            self._advance()
            expr = self._parse_expression()
            decorators.append(Decorator(expr=expr, line=line))
            if self._check(NEWLINE):
                self._advance()
        if self._check_kw("def"):
            return self._parse_function_def(is_async=False, decorators=decorators)
        if self._check_kw("async"):
            self._advance()
            if self._check_kw("def"):
                return self._parse_function_def(is_async=True, decorators=decorators)
            self._error("expected 'def' after 'async' in decorated definition")
            self._skip_to_next_statement()
            return None
        if self._check_kw("class"):
            return self._parse_class_def(decorators=decorators)
        self._error("expected function or class after decorator(s)")
        self._skip_to_next_statement()
        return None

    # ---- simple statements ------------------------------------------

    def _parse_return_stmt(self) -> ReturnStatement:
        line = self._peek().line
        self._advance()
        value: Optional[Any] = None
        if not self._is_statement_end():
            value = self._parse_expression_list()
        stmt = ReturnStatement(value=value, line=line)
        self._consume_newline()
        return stmt

    def _parse_raise_stmt(self) -> RaiseStatement:
        line = self._peek().line
        self._advance()
        exc: Optional[Any] = None
        cause: Optional[Any] = None
        if not self._is_statement_end():
            exc = self._parse_expression()
            if self._match_kw("from"):
                cause = self._parse_expression()
        stmt = RaiseStatement(exc=exc, cause=cause, line=line)
        self._consume_newline()
        return stmt

    def _parse_import_stmt(self) -> ImportStatement:
        line = self._peek().line
        self._advance()  # 'import'
        names = [self._parse_dotted_as_name()]
        while self._match_delim(","):
            names.append(self._parse_dotted_as_name())
        stmt = ImportStatement(names=names, line=line)
        self._consume_newline()
        return stmt

    def _parse_dotted_as_name(self) -> Tup[str, Optional[str]]:
        name = self._parse_dotted_name()
        alias: Optional[str] = None
        if self._match_kw("as"):
            alias = self._expect(IDENTIFIER).value
        return (name, alias)

    def _parse_dotted_name(self) -> str:
        parts = [self._expect(IDENTIFIER).value]
        while self._match_delim("."):
            parts.append(self._expect(IDENTIFIER).value)
        return ".".join(parts)

    def _parse_from_stmt(self) -> ImportFromStatement:
        line = self._peek().line
        self._advance()  # 'from'
        level = 0
        # leading dots — each `.` is one level, each `...` (ellipsis-as-delimiter) is three
        while True:
            if self._check_delim("."):
                self._advance()
                level += 1
                continue
            if self._check_delim("..."):
                self._advance()
                level += 3
                continue
            break
        module: Optional[str] = None
        if self._check(IDENTIFIER):
            module = self._parse_dotted_name()
        self._expect_kw("import")
        names: List[Tup[str, Optional[str]]] = []
        if self._match_op("*"):
            names.append(("*", None))
        else:
            has_paren = self._match_delim("(") is not None
            while self._check(NEWLINE):
                self._advance()
            names.append(self._parse_import_as_name())
            while self._match_delim(","):
                while self._check(NEWLINE):
                    self._advance()
                if has_paren and self._check_delim(")"):
                    break
                names.append(self._parse_import_as_name())
            while self._check(NEWLINE):
                self._advance()
            if has_paren:
                self._expect_delim(")")
        stmt = ImportFromStatement(module=module, names=names, level=level, line=line)
        self._consume_newline()
        return stmt

    def _parse_import_as_name(self) -> Tup[str, Optional[str]]:
        name = self._expect(IDENTIFIER).value
        alias: Optional[str] = None
        if self._match_kw("as"):
            alias = self._expect(IDENTIFIER).value
        return (name, alias)

    def _parse_global_stmt(self) -> GlobalStatement:
        line = self._peek().line
        self._advance()
        names = [self._expect(IDENTIFIER).value]
        while self._match_delim(","):
            names.append(self._expect(IDENTIFIER).value)
        stmt = GlobalStatement(names=names, line=line)
        self._consume_newline()
        return stmt

    def _parse_nonlocal_stmt(self) -> NonlocalStatement:
        line = self._peek().line
        self._advance()
        names = [self._expect(IDENTIFIER).value]
        while self._match_delim(","):
            names.append(self._expect(IDENTIFIER).value)
        stmt = NonlocalStatement(names=names, line=line)
        self._consume_newline()
        return stmt

    def _parse_del_stmt(self) -> DeleteStatement:
        line = self._peek().line
        self._advance()
        targets = [self._parse_expression()]
        while self._match_delim(","):
            targets.append(self._parse_expression())
        stmt = DeleteStatement(targets=targets, line=line)
        self._consume_newline()
        return stmt

    def _parse_assert_stmt(self) -> AssertStatement:
        line = self._peek().line
        self._advance()
        test = self._parse_expression()
        msg: Optional[Any] = None
        if self._match_delim(","):
            msg = self._parse_expression()
        stmt = AssertStatement(test=test, msg=msg, line=line)
        self._consume_newline()
        return stmt

    def _parse_yield_stmt(self) -> Any:
        expr = self._parse_yield_expr()
        self._consume_newline()
        return expr

    # ---- assignment / expression statement --------------------------

    def _parse_expr_or_assign_stmt(self) -> Any:
        line = self._peek().line
        expr = self._parse_expression_list()
        # Annotated assignment: target : annotation [= value]
        if self._check_delim(":"):
            self._advance()
            annotation = self._parse_expression()
            value: Optional[Any] = None
            if self._match_delim("="):
                value = self._parse_expression_list()
            stmt = AnnAssignStatement(
                target=expr, annotation=annotation, value=value, line=line,
            )
            self._consume_newline()
            return stmt
        # Augmented assignment
        if self._check(OPERATOR) and self._peek().value in _AUG_OPS:
            op = self._advance().value
            value = self._parse_expression_list()
            stmt = AugAssignStatement(target=expr, op=op, value=value, line=line)
            self._consume_newline()
            return stmt
        # Plain (possibly chained) assignment
        if self._check_delim("="):
            targets = [expr]
            value_expr = None
            while self._match_delim("="):
                next_expr = self._parse_expression_list()
                if self._check_delim("="):
                    targets.append(next_expr)
                else:
                    value_expr = next_expr
                    break
            stmt = AssignStatement(targets=targets, value=value_expr, line=line)
            self._consume_newline()
            return stmt
        # Plain expression statement
        stmt = ExprStatement(value=expr, line=line)
        self._consume_newline()
        return stmt

    def _is_statement_end(self) -> bool:
        return (
            self._check(NEWLINE)
            or self._check(DEDENT)
            or self._check_delim(";")
            or self._at_end()
        )

    # ---- parameter list (function definitions) ----------------------

    def _parse_parameters(self) -> List[Parameter]:
        params: List[Parameter] = []
        pending_pos: List[Parameter] = []
        section = "pos"  # 'pos', 'after_slash', 'kwonly'

        while not self._check_delim(")") and not self._at_end():
            # `/` — positional-only marker: everything seen so far is posonly
            if self._check_op("/"):
                self._advance()
                for p in pending_pos:
                    p.kind_marker = "posonly"
                params.extend(pending_pos)
                pending_pos = []
                section = "after_slash"
                if not self._match_delim(","):
                    break
                continue
            # `*` — vararg or bare-* (kwonly marker)
            if self._check_op("*"):
                self._advance()
                if pending_pos:
                    params.extend(pending_pos)
                    pending_pos = []
                if self._check(IDENTIFIER):
                    line = self._peek().line
                    name = self._advance().value
                    annotation = self._parse_optional_annotation()
                    params.append(Parameter(
                        name=name, annotation=annotation,
                        kind_marker="vararg", line=line,
                    ))
                section = "kwonly"
                if not self._match_delim(","):
                    break
                continue
            # `**kwargs`
            if self._check_op("**"):
                self._advance()
                if pending_pos:
                    params.extend(pending_pos)
                    pending_pos = []
                line = self._peek().line
                name = self._expect(IDENTIFIER).value
                annotation = self._parse_optional_annotation()
                params.append(Parameter(
                    name=name, annotation=annotation,
                    kind_marker="kwarg", line=line,
                ))
                self._match_delim(",")
                break
            # regular parameter
            line = self._peek().line
            name = self._expect(IDENTIFIER).value
            annotation = self._parse_optional_annotation()
            default: Optional[Any] = None
            if self._match_delim("="):
                default = self._parse_expression()
            kind = "kwonly" if section == "kwonly" else "pos"
            p = Parameter(
                name=name, annotation=annotation, default=default,
                kind_marker=kind, line=line,
            )
            if section == "pos":
                pending_pos.append(p)
            else:
                params.append(p)
            if not self._match_delim(","):
                break
        params.extend(pending_pos)
        return params

    def _parse_optional_annotation(self) -> Optional[Any]:
        if self._match_delim(":"):
            return self._parse_expression()
        return None

    # ---- expressions: precedence climbing ---------------------------

    def _parse_expression_list(self) -> Any:
        line = self._peek().line
        first = self._parse_expression()
        if not self._check_delim(","):
            return first
        elements = [first]
        while self._match_delim(","):
            if self._is_expr_list_end():
                break
            elements.append(self._parse_expression())
        return TupleExpr(elements=elements, line=line)

    def _is_expr_list_end(self) -> bool:
        if self._check(NEWLINE) or self._check(DEDENT) or self._at_end():
            return True
        if self._check_delim(")") or self._check_delim("]") or self._check_delim("}"):
            return True
        if self._check_delim(":") or self._check_delim(";") or self._check_delim("="):
            return True
        return False

    def _parse_expression(self) -> Any:
        if self._check_kw("lambda"):
            return self._parse_lambda()
        return self._parse_ternary()

    def _parse_ternary(self) -> Any:
        expr = self._parse_or()
        if self._check_kw("if"):
            line = _line_of(expr, self._peek().line)
            self._advance()
            test = self._parse_or()
            self._expect_kw("else")
            orelse = self._parse_expression()
            return IfExpr(test=test, body=expr, orelse=orelse, line=line)
        return expr

    def _parse_lambda(self) -> Lambda:
        line = self._peek().line
        self._expect_kw("lambda")
        params = self._parse_lambda_parameters()
        self._expect_delim(":")
        body = self._parse_expression()
        return Lambda(params=params, body=body, line=line)

    def _parse_lambda_parameters(self) -> List[Parameter]:
        params: List[Parameter] = []
        in_kwonly = False
        while not self._check_delim(":") and not self._at_end():
            if self._check_op("/"):
                self._advance()
                for p in params:
                    if p.kind_marker == "pos":
                        p.kind_marker = "posonly"
                self._match_delim(",")
                continue
            if self._check_op("**"):
                self._advance()
                name = self._expect(IDENTIFIER).value
                params.append(Parameter(name=name, kind_marker="kwarg", line=self._peek().line))
                self._match_delim(",")
                break
            if self._check_op("*"):
                self._advance()
                if self._check(IDENTIFIER):
                    name = self._advance().value
                    params.append(Parameter(name=name, kind_marker="vararg", line=self._peek().line))
                in_kwonly = True
                if not self._match_delim(","):
                    break
                continue
            name = self._expect(IDENTIFIER).value
            default: Optional[Any] = None
            if self._match_delim("="):
                default = self._parse_expression()
            params.append(Parameter(
                name=name, default=default,
                kind_marker="kwonly" if in_kwonly else "pos",
                line=self._peek().line,
            ))
            if not self._match_delim(","):
                break
        return params

    def _parse_or(self) -> Any:
        left = self._parse_and()
        if self._check_kw("or"):
            line = _line_of(left, self._peek().line)
            values = [left]
            while self._match_kw("or"):
                values.append(self._parse_and())
            return BoolOp(op="or", values=values, line=line)
        return left

    def _parse_and(self) -> Any:
        left = self._parse_not()
        if self._check_kw("and"):
            line = _line_of(left, self._peek().line)
            values = [left]
            while self._match_kw("and"):
                values.append(self._parse_not())
            return BoolOp(op="and", values=values, line=line)
        return left

    def _parse_not(self) -> Any:
        if self._check_kw("not"):
            line = self._peek().line
            self._advance()
            operand = self._parse_not()
            return UnaryOp(op="not", operand=operand, line=line)
        return self._parse_comparison()

    def _parse_comparison(self) -> Any:
        left = self._parse_bitor()
        ops: List[str] = []
        comparators: List[Any] = []
        while self._at_compare_op():
            ops.append(self._consume_compare_op())
            comparators.append(self._parse_bitor())
        if ops:
            return Compare(
                left=left, ops=ops, comparators=comparators,
                line=_line_of(left, self._peek().line),
            )
        return left

    def _at_compare_op(self) -> bool:
        tok = self._peek()
        if tok.type == OPERATOR and tok.value in ("==", "!=", "<", ">", "<=", ">="):
            return True
        if tok.type == KEYWORD:
            if tok.value in ("in", "is"):
                return True
            if tok.value == "not":
                nxt = self._peek(1)
                if nxt.type == KEYWORD and nxt.value == "in":
                    return True
        return False

    def _consume_compare_op(self) -> str:
        tok = self._peek()
        if tok.type == OPERATOR:
            self._advance()
            return tok.value
        if tok.value == "in":
            self._advance()
            return "in"
        if tok.value == "is":
            self._advance()
            if self._match_kw("not"):
                return "is not"
            return "is"
        if tok.value == "not":
            self._advance()
            self._expect_kw("in")
            return "not in"
        return "?"

    def _parse_bitor(self) -> Any:
        left = self._parse_bitxor()
        while self._check_op("|"):
            line = _line_of(left, self._peek().line)
            self._advance()
            right = self._parse_bitxor()
            left = BinaryOp(op="|", left=left, right=right, line=line)
        return left

    def _parse_bitxor(self) -> Any:
        left = self._parse_bitand()
        while self._check_op("^"):
            line = _line_of(left, self._peek().line)
            self._advance()
            right = self._parse_bitand()
            left = BinaryOp(op="^", left=left, right=right, line=line)
        return left

    def _parse_bitand(self) -> Any:
        left = self._parse_shift()
        while self._check_op("&"):
            line = _line_of(left, self._peek().line)
            self._advance()
            right = self._parse_shift()
            left = BinaryOp(op="&", left=left, right=right, line=line)
        return left

    def _parse_shift(self) -> Any:
        left = self._parse_arith()
        while self._check_op("<<") or self._check_op(">>"):
            op = self._advance().value
            line = _line_of(left, self._peek().line)
            right = self._parse_arith()
            left = BinaryOp(op=op, left=left, right=right, line=line)
        return left

    def _parse_arith(self) -> Any:
        left = self._parse_term()
        while self._check_op("+") or self._check_op("-"):
            op = self._advance().value
            line = _line_of(left, self._peek().line)
            right = self._parse_term()
            left = BinaryOp(op=op, left=left, right=right, line=line)
        return left

    def _parse_term(self) -> Any:
        left = self._parse_factor()
        while (
            self._check_op("*") or self._check_op("/") or self._check_op("//")
            or self._check_op("%") or self._check_op("@")
        ):
            op = self._advance().value
            line = _line_of(left, self._peek().line)
            right = self._parse_factor()
            left = BinaryOp(op=op, left=left, right=right, line=line)
        return left

    def _parse_factor(self) -> Any:
        if self._check_op("+") or self._check_op("-") or self._check_op("~"):
            tok = self._advance()
            operand = self._parse_factor()
            return UnaryOp(op=tok.value, operand=operand, line=tok.line)
        return self._parse_power()

    def _parse_power(self) -> Any:
        base = self._parse_await()
        if self._check_op("**"):
            line = _line_of(base, self._peek().line)
            self._advance()
            exp = self._parse_factor()  # right-associative; factor includes unary
            return BinaryOp(op="**", left=base, right=exp, line=line)
        return base

    def _parse_await(self) -> Any:
        if self._check_kw("await"):
            line = self._peek().line
            self._advance()
            value = self._parse_atom_with_trailers()
            return Await(value=value, line=line)
        return self._parse_atom_with_trailers()

    # ---- atom + trailers --------------------------------------------

    def _parse_atom_with_trailers(self) -> Any:
        atom = self._parse_atom()
        while True:
            if self._check_delim("("):
                atom = self._parse_call_trailer(atom)
            elif self._check_delim("."):
                self._advance()
                tok = self._peek()
                if tok.type == IDENTIFIER or tok.type == KEYWORD:
                    self._advance()
                    atom = Attribute(
                        value=atom, attr=tok.value,
                        line=_line_of(atom, tok.line),
                    )
                else:
                    self._error("expected attribute name after '.'")
                    atom = ErrorNode(message="bad attribute", line=tok.line)
            elif self._check_delim("["):
                atom = self._parse_subscript_trailer(atom)
            else:
                break
        return atom

    def _parse_call_trailer(self, func: Any) -> Call:
        self._expect_delim("(")
        args: List[Argument] = []
        if not self._check_delim(")"):
            args.append(self._parse_argument())
            while self._match_delim(","):
                if self._check_delim(")"):
                    break
                args.append(self._parse_argument())
        self._expect_delim(")")
        return Call(func=func, args=args, line=_line_of(func, self._peek().line))

    def _parse_argument(self) -> Argument:
        line = self._peek().line
        if self._match_op("**"):
            value = self._parse_expression()
            return Argument(value=value, is_double_star=True, line=line)
        if self._match_op("*"):
            value = self._parse_expression()
            return Argument(value=value, is_star=True, line=line)
        # Keyword arg pattern: IDENTIFIER '=' value
        if self._check(IDENTIFIER):
            saved = self._stream.save()
            name_tok = self._advance()
            if self._check_delim("=") and not self._check(OPERATOR, "=="):
                self._advance()
                value = self._parse_expression()
                return Argument(value=value, name=name_tok.value, line=line)
            self._stream.restore(saved)
        value = self._parse_expression()
        # Single-argument generator expression: `func(x for x in xs)`
        if self._check_kw("for") or self._check_kw("async"):
            gens = self._parse_comp_clauses()
            value = Comprehension(
                comprehension_kind="gen", elt=value,
                generators=gens, line=line,
            )
        return Argument(value=value, line=line)

    def _parse_subscript_trailer(self, value: Any) -> SubscriptExpr:
        self._expect_delim("[")
        slice_expr = self._parse_subscript_inner()
        self._expect_delim("]")
        return SubscriptExpr(
            value=value, slice=slice_expr,
            line=_line_of(value, self._peek().line),
        )

    def _parse_subscript_inner(self) -> Any:
        elts = [self._parse_slice_or_expr()]
        while self._match_delim(","):
            if self._check_delim("]"):
                break
            elts.append(self._parse_slice_or_expr())
        if len(elts) == 1:
            return elts[0]
        return TupleExpr(elements=elts, line=_line_of(elts[0], 0))

    def _parse_slice_or_expr(self) -> Any:
        line = self._peek().line
        lower: Optional[Any] = None
        upper: Optional[Any] = None
        step: Optional[Any] = None
        if not self._check_delim(":"):
            lower = self._parse_expression()
        if not self._match_delim(":"):
            return lower
        if not self._check_delim(":") and not self._check_delim(",") and not self._check_delim("]"):
            upper = self._parse_expression()
        if self._match_delim(":"):
            if not self._check_delim(",") and not self._check_delim("]"):
                step = self._parse_expression()
        return Slice(lower=lower, upper=upper, step=step, line=line)

    # ---- atom -------------------------------------------------------

    def _parse_atom(self) -> Any:
        tok = self._peek()
        line = tok.line

        if tok.type == NUMBER:
            self._advance()
            return Constant(value=tok.value, value_type="number", line=line)
        if tok.type == STRING:
            return self._parse_string_chain()
        if tok.type == KEYWORD:
            if tok.value == "True":
                self._advance()
                return Constant(value=True, value_type="bool", line=line)
            if tok.value == "False":
                self._advance()
                return Constant(value=False, value_type="bool", line=line)
            if tok.value == "None":
                self._advance()
                return Constant(value=None, value_type="none", line=line)
            if tok.value == "yield":
                return self._parse_yield_expr()
            if tok.value == "lambda":
                return self._parse_lambda()
            self._error("unexpected keyword " + repr(tok.value) + " in expression")
            self._advance()
            return ErrorNode(message="unexpected keyword " + tok.value, line=line)
        if tok.type == IDENTIFIER:
            self._advance()
            if self._check_op(":="):
                self._advance()
                value = self._parse_expression()
                return WalrusExpr(
                    target=Name(id=tok.value, line=line),
                    value=value, line=line,
                )
            return Name(id=tok.value, line=line)
        if tok.type == DELIMITER:
            if tok.value == "(":
                return self._parse_paren_atom()
            if tok.value == "[":
                return self._parse_list_atom()
            if tok.value == "{":
                return self._parse_dict_or_set_atom()
            if tok.value == "...":
                self._advance()
                return Constant(value="...", value_type="ellipsis", line=line)
        if tok.type == OPERATOR and tok.value == "*":
            self._advance()
            value = self._parse_expression()
            return StarredExpr(value=value, line=line)
        if tok.type == ERROR:
            self._advance()
            return ErrorNode(message="tokenizer ERROR: " + tok.value, line=line)
        self._error("unexpected token " + repr(tok.value) + " in expression")
        self._advance()
        return ErrorNode(message="unexpected " + str(tok.value), line=line)

    def _parse_string_chain(self) -> Constant:
        tok = self._peek()
        line = tok.line
        first_value = self._advance().value
        parts = [first_value]
        while self._check(STRING):
            parts.append(self._advance().value)
        # Detect the prefix of the first chunk to classify the resulting constant.
        i = 0
        while i < len(first_value) and first_value[i] not in "\"'":
            i += 1
        prefix = first_value[:i].lower()
        if "b" in prefix:
            vt = "bytes"
        elif "f" in prefix:
            vt = "fstring"
        else:
            vt = "string"
        return Constant(value="".join(parts), value_type=vt, line=line)

    def _parse_paren_atom(self) -> Any:
        line = self._peek().line
        self._expect_delim("(")
        if self._match_delim(")"):
            return TupleExpr(elements=[], line=line)
        if self._check_kw("yield"):
            expr = self._parse_yield_expr()
            self._expect_delim(")")
            return expr
        first = self._parse_starred_or_expr()
        if self._check_kw("for") or self._check_kw("async"):
            gens = self._parse_comp_clauses()
            self._expect_delim(")")
            return Comprehension(
                comprehension_kind="gen", elt=first,
                generators=gens, line=line,
            )
        if self._check_delim(","):
            elements = [first]
            while self._match_delim(","):
                if self._check_delim(")"):
                    break
                elements.append(self._parse_starred_or_expr())
            self._expect_delim(")")
            return TupleExpr(elements=elements, line=line)
        self._expect_delim(")")
        return first

    def _parse_starred_or_expr(self) -> Any:
        if self._check_op("*"):
            line = self._peek().line
            self._advance()
            value = self._parse_expression()
            return StarredExpr(value=value, line=line)
        return self._parse_expression()

    def _parse_list_atom(self) -> Any:
        line = self._peek().line
        self._expect_delim("[")
        if self._match_delim("]"):
            return ListExpr(elements=[], line=line)
        first = self._parse_starred_or_expr()
        if self._check_kw("for") or self._check_kw("async"):
            gens = self._parse_comp_clauses()
            self._expect_delim("]")
            return Comprehension(
                comprehension_kind="list", elt=first,
                generators=gens, line=line,
            )
        elements = [first]
        while self._match_delim(","):
            if self._check_delim("]"):
                break
            elements.append(self._parse_starred_or_expr())
        self._expect_delim("]")
        return ListExpr(elements=elements, line=line)

    def _parse_dict_or_set_atom(self) -> Any:
        line = self._peek().line
        self._expect_delim("{")
        if self._match_delim("}"):
            return DictExpr(keys=[], values=[], line=line)
        if self._check_op("**"):
            return self._parse_dict_tail_starting_with_unpack(line)
        first = self._parse_expression()
        if self._match_delim(":"):
            first_val = self._parse_expression()
            if self._check_kw("for") or self._check_kw("async"):
                gens = self._parse_comp_clauses()
                self._expect_delim("}")
                return Comprehension(
                    comprehension_kind="dict", key=first, value=first_val,
                    generators=gens, line=line,
                )
            keys: List[Any] = [first]
            values: List[Any] = [first_val]
            while self._match_delim(","):
                if self._check_delim("}"):
                    break
                if self._match_op("**"):
                    keys.append(None)
                    values.append(self._parse_expression())
                else:
                    keys.append(self._parse_expression())
                    self._expect_delim(":")
                    values.append(self._parse_expression())
            self._expect_delim("}")
            return DictExpr(keys=keys, values=values, line=line)
        if self._check_kw("for") or self._check_kw("async"):
            gens = self._parse_comp_clauses()
            self._expect_delim("}")
            return Comprehension(
                comprehension_kind="set", elt=first,
                generators=gens, line=line,
            )
        elements = [first]
        while self._match_delim(","):
            if self._check_delim("}"):
                break
            elements.append(self._parse_expression())
        self._expect_delim("}")
        return SetExpr(elements=elements, line=line)

    def _parse_dict_tail_starting_with_unpack(self, line: int) -> DictExpr:
        keys: List[Any] = []
        values: List[Any] = []
        self._advance()  # '**'
        values.append(self._parse_expression())
        keys.append(None)
        while self._match_delim(","):
            if self._check_delim("}"):
                break
            if self._match_op("**"):
                keys.append(None)
                values.append(self._parse_expression())
            else:
                keys.append(self._parse_expression())
                self._expect_delim(":")
                values.append(self._parse_expression())
        self._expect_delim("}")
        return DictExpr(keys=keys, values=values, line=line)

    def _parse_comp_clauses(self) -> List[Dict[str, Any]]:
        gens: List[Dict[str, Any]] = []
        while self._check_kw("for") or self._check_kw("async"):
            is_async = False
            if self._match_kw("async"):
                is_async = True
                if not self._check_kw("for"):
                    break
            self._expect_kw("for")
            target = self._parse_target_list()
            self._expect_kw("in")
            iter_expr = self._parse_or()
            ifs: List[Any] = []
            while self._match_kw("if"):
                ifs.append(self._parse_or())
            gens.append({
                "target": target, "iter": iter_expr,
                "ifs": ifs, "is_async": is_async,
            })
        return gens

    # ---- yield expression -------------------------------------------

    def _parse_yield_expr(self) -> YieldStatement:
        line = self._peek().line
        self._expect_kw("yield")
        if self._match_kw("from"):
            value = self._parse_expression()
            return YieldStatement(value=value, is_from=True, line=line)
        if (
            self._is_statement_end()
            or self._check_delim(")") or self._check_delim("]")
            or self._check_delim("}") or self._check_delim(",")
        ):
            return YieldStatement(value=None, is_from=False, line=line)
        value = self._parse_expression_list()
        return YieldStatement(value=value, is_from=False, line=line)

    # ---- assignment targets -----------------------------------------

    def _parse_target_list(self) -> Any:
        line = self._peek().line
        first = self._parse_target()
        if not self._check_delim(","):
            return first
        elements = [first]
        while self._match_delim(","):
            if self._is_expr_list_end() or self._check_kw("in"):
                break
            elements.append(self._parse_target())
        return TupleExpr(elements=elements, line=line)

    def _parse_target(self) -> Any:
        if self._check_op("*"):
            line = self._peek().line
            self._advance()
            value = self._parse_atom_with_trailers()
            return StarredExpr(value=value, line=line)
        return self._parse_atom_with_trailers()

    # ---- match statement (PEP 634, soft keyword) --------------------

    def _looks_like_match(self) -> bool:
        if not (self._check(IDENTIFIER) and self._peek().value == "match"):
            return False
        saved = self._stream.save()
        try:
            self._advance()
            depth = 0
            found_colon = False
            while not self._at_end():
                t = self._peek()
                if t.type == DELIMITER:
                    if t.value in "([{":
                        depth += 1
                    elif t.value in ")]}":
                        depth -= 1
                    elif t.value == ":" and depth == 0:
                        found_colon = True
                        break
                    elif t.value in (";", "=") and depth == 0:
                        return False
                if t.type == NEWLINE and depth == 0:
                    return False
                self._advance()
            if not found_colon:
                return False
            self._advance()  # past ':'
            while self._check(NEWLINE):
                self._advance()
            if not self._check(INDENT):
                return False
            self._advance()
            while self._check(NEWLINE):
                self._advance()
            return self._check(IDENTIFIER) and self._peek().value == "case"
        finally:
            self._stream.restore(saved)

    def _parse_match_stmt(self) -> MatchStatement:
        line = self._peek().line
        self._advance()  # 'match'
        subject = self._parse_expression_list()
        self._expect_delim(":")
        if self._check(NEWLINE):
            self._advance()
        if not self._match(INDENT):
            self._error("expected indented block after match statement")
            self._skip_to_next_statement()
            return MatchStatement(subject=subject, cases=[], line=line)
        cases: List[Dict[str, Any]] = []
        while not self._check(DEDENT) and not self._at_end():
            if self._check(NEWLINE):
                self._advance()
                continue
            if self._check(IDENTIFIER) and self._peek().value == "case":
                cases.append(self._parse_case_clause())
            else:
                self._error("expected 'case' clause in match block")
                self._skip_to_next_statement()
        self._match(DEDENT)
        return MatchStatement(subject=subject, cases=cases, line=line)

    def _parse_case_clause(self) -> Dict[str, Any]:
        line = self._peek().line
        self._advance()  # 'case'
        pattern = self._parse_pattern()
        guard: Optional[Any] = None
        if self._match_kw("if"):
            guard = self._parse_expression()
        self._expect_delim(":")
        body = self._parse_suite()
        return {"pattern": pattern, "guard": guard, "body": body, "line": line}

    def _parse_pattern(self) -> Any:
        first = self._parse_pattern_alternative()
        if not self._check_op("|"):
            return first
        alts = [first]
        while self._match_op("|"):
            alts.append(self._parse_pattern_alternative())
        return BoolOp(op="|", values=alts, line=_line_of(first, 0))

    def _parse_pattern_alternative(self) -> Any:
        # Patterns are parsed at the `or_test` level — *below* ternary —
        # so the `if` of `case X if guard:` is not stolen by an x-if-y-else
        # expression. Real PEP 634 capture/class/mapping patterns need
        # dedicated nodes, but parsing as an expression captures the
        # surface structure for the walker.
        return self._parse_or()


# ---- helpers --------------------------------------------------------


def _line_of(node: Any, default: int) -> int:
    return getattr(node, "line", default) or default


class _RecoveryAbort(Exception):
    """Internal: raised from deep inside a statement to bail out to the
    next statement boundary for error recovery. Not currently raised by
    any rule — kept as a hook for future hard-error recovery."""
