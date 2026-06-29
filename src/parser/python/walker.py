"""Python AST walker — turns the tree produced by `PythonParser` into
nodes and edges in a language-agnostic `Graph`.

The walker is deliberately thin: it does not resolve names across
files. Every reference-style edge (CALLS, IMPORTS, EXTENDS, DECORATES,
CATCHES, RAISES) is emitted with `is_resolved=False` and carries the
unresolved target as a plain string. A later resolution pass will
rewrite those target ids once it knows what each name refers to.
"""

from typing import Any, Dict, List, Optional

from graph.edge import Edge
from graph.graph import Graph
from graph.node import Node


class Walker:
    """AST -> Graph traversal.

    Maintains a context stack so that a `Call` discovered deep inside a
    nested function attributes its `CALLS` edge to the correct enclosing
    function rather than to a shallower scope. The walker is stateful
    but re-entrant: `walk()` resets all internal state.
    """

    def __init__(self) -> None:
        self._graph: Optional[Graph] = None
        self._file_path: str = ""
        self._module_id: str = ""
        # Stack of class names currently being visited. None at module level.
        self._class_stack: List[str] = []
        # Stack of function node ids currently being visited.
        self._function_stack: List[str] = []
        # Per-base-id counter for edge id deduplication.
        self._edge_id_counts: Dict[str, int] = {}

    # ---- public API --------------------------------------------------

    def walk(self, tree: Any, file_path: str, graph: Graph) -> Graph:
        """Walk the Module AST `tree`, attribute everything to
        `file_path`, and populate `graph` in place. Returns the graph
        for chaining."""
        self._graph = graph
        self._file_path = file_path
        self._class_stack = []
        self._function_stack = []
        self._edge_id_counts = {}
        self._module_id = Node.make_id(file_path, "", "")
        self._visit_module(tree)
        return graph

    # ---- context properties -----------------------------------------

    @property
    def current_file(self) -> str:
        return self._file_path

    @property
    def current_class(self) -> Optional[str]:
        return self._class_stack[-1] if self._class_stack else None

    @property
    def current_function(self) -> Optional[str]:
        return self._function_stack[-1] if self._function_stack else None

    # ---- generic dispatch -------------------------------------------

    def _visit(self, node: Any) -> None:
        if node is None:
            return
        kind = getattr(node, "kind", None)
        if kind is None:
            return
        if kind == "Module":
            self._visit_module(node)
        elif kind == "FunctionDef":
            self._visit_function_def(node, is_async=False)
        elif kind == "AsyncFunctionDef":
            self._visit_function_def(node, is_async=True)
        elif kind == "ClassDef":
            self._visit_class_def(node)
        elif kind == "ImportStatement":
            self._visit_import(node)
        elif kind == "ImportFromStatement":
            self._visit_import_from(node)
        elif kind == "Call":
            self._visit_call(node)
        elif kind == "TryStatement":
            self._visit_try(node)
        elif kind == "RaiseStatement":
            self._visit_raise(node)
        elif kind == "AssignStatement" or kind == "AnnAssignStatement":
            self._visit_assign(node)
        else:
            # Unhandled construct — recurse so we still find Calls,
            # Raises, function defs, etc. inside it.
            self._recurse_into(node)

    def _recurse_into(self, node: Any) -> None:
        """Walk every dataclass field of `node` and visit any AST
        children. Lists, tuples, and dicts of children are unwrapped."""
        if node is None or not hasattr(node, "__dataclass_fields__"):
            return
        for fname in node.__dataclass_fields__:
            self._visit_value(getattr(node, fname))

    def _visit_value(self, value: Any) -> None:
        if value is None:
            return
        if hasattr(value, "kind"):
            self._visit(value)
            return
        if isinstance(value, list):
            for item in value:
                self._visit_value(item)
            return
        if isinstance(value, tuple):
            for item in value:
                self._visit_value(item)
            return
        if isinstance(value, dict):
            for v in value.values():
                self._visit_value(v)
            return
        # primitive scalar — nothing to traverse

    # ---- per-construct visitors -------------------------------------

    def _visit_module(self, node: Any) -> None:
        # A module node anchors module-level edges (IMPORTS, etc.).
        module_node = Node(
            id=self._module_id,
            name=self._module_name_from_path(self._file_path),
            type="module",
            file_path=self._file_path,
            line_number=getattr(node, "line", 1) or 1,
            language="python",
            docstring=self._get_docstring(getattr(node, "body", [])),
        )
        self._add_node(module_node)
        for stmt in getattr(node, "body", []):
            self._visit(stmt)

    def _visit_function_def(self, node: Any, is_async: bool) -> None:
        fn_name = node.name
        class_context = self.current_class or ""
        fn_id = Node.make_id(self._file_path, class_context, fn_name)

        docstring = self._get_docstring(getattr(node, "body", []))
        params = [getattr(p, "name", "") for p in getattr(node, "params", [])]
        decorators = [
            self._extract_decorator_name(d)
            for d in getattr(node, "decorators", [])
        ]

        fn_node_type = "function"
        fn_node = Node(
            id=fn_id,
            name=fn_name,
            type=fn_node_type,
            file_path=self._file_path,
            line_number=getattr(node, "line", 0),
            language="python",
            docstring=docstring,
            metadata={
                "params": params,
                "is_async": is_async,
                "decorators": [d for d in decorators if d],
            },
        )
        self._add_node(fn_node)

        # CONTAINS — only when the function lives inside a class (as a
        # method, source=class) or inside another function (nested,
        # source=enclosing function). Module-level functions get no
        # CONTAINS edge per spec.
        if self.current_function is not None:
            # Nested: outer function owns this one (whether or not we're
            # also inside a class).
            self._add_edge(
                source_id=self.current_function,
                relationship="CONTAINS",
                target_id=fn_id,
                is_resolved=True,
                confidence=1.0,
            )
        elif self.current_class is not None:
            class_id = Node.make_id(self._file_path, self.current_class, "")
            self._add_edge(
                source_id=class_id,
                relationship="CONTAINS",
                target_id=fn_id,
                is_resolved=True,
                confidence=1.0,
            )

        # DECORATES edges (decorator -> this function)
        self._emit_decorates_edges(fn_id, decorators)

        # Recurse into the function body with this function on the stack
        # so nested Calls / Raises / etc. attribute correctly.
        self._function_stack.append(fn_id)
        try:
            for stmt in getattr(node, "body", []):
                self._visit(stmt)
        finally:
            self._function_stack.pop()

    def _visit_class_def(self, node: Any) -> None:
        class_name = node.name
        class_id = Node.make_id(self._file_path, class_name, "")

        bases = getattr(node, "bases", [])
        base_names: List[str] = []
        for base in bases:
            # Class bases come from the parser as `Argument` wrappers
            # whose `.value` holds the actual expression. Be defensive
            # in case a raw expression slips through.
            base_expr = getattr(base, "value", base)
            bname = self._expr_to_name_string(base_expr)
            if bname:
                base_names.append(bname)

        decorators = [
            self._extract_decorator_name(d)
            for d in getattr(node, "decorators", [])
        ]

        docstring = self._get_docstring(getattr(node, "body", []))

        class_node = Node(
            id=class_id,
            name=class_name,
            type="class",
            file_path=self._file_path,
            line_number=getattr(node, "line", 0),
            language="python",
            docstring=docstring,
            metadata={
                "bases": base_names,
                "decorators": [d for d in decorators if d],
            },
        )
        self._add_node(class_node)

        # EXTENDS edges — one per base class
        for bname in base_names:
            self._add_edge(
                source_id=class_id,
                relationship="EXTENDS",
                target_id=bname,
                is_resolved=False,
                confidence=1.0,
            )

        # DECORATES edges — one per decorator
        self._emit_decorates_edges(class_id, decorators)

        # Descend into the class body with this class on the stack so
        # method `CONTAINS` edges attribute back to it.
        self._class_stack.append(class_name)
        try:
            for stmt in getattr(node, "body", []):
                self._visit(stmt)
        finally:
            self._class_stack.pop()

    def _visit_import(self, node: Any) -> None:
        for name, alias in getattr(node, "names", []):
            self._add_edge(
                source_id=self._module_id,
                relationship="IMPORTS",
                target_id=name,
                is_resolved=False,
                confidence=1.0,
                metadata={"alias": alias, "original_name": name},
            )

    def _visit_import_from(self, node: Any) -> None:
        module = getattr(node, "module", None)
        level = getattr(node, "level", 0) or 0
        module_str = module if module else ""
        for name, alias in getattr(node, "names", []):
            target_id = module_str + "::" + name
            self._add_edge(
                source_id=self._module_id,
                relationship="IMPORTS",
                target_id=target_id,
                is_resolved=False,
                confidence=1.0,
                metadata={
                    "module": module,
                    "alias": alias,
                    "level": level,
                },
            )

    def _visit_call(self, node: Any) -> None:
        # Always recurse into the call's children first so a Call nested
        # inside a Call's args (e.g. `outer(inner())`) is also walked.
        # Then emit the edge for *this* Call if we're inside a function.
        target_name, call_type = self._extract_call_target(node)
        if self.current_function is not None and target_name:
            arg_count = len(getattr(node, "args", []) or [])
            self._add_edge(
                source_id=self.current_function,
                relationship="CALLS",
                target_id=target_name,
                is_resolved=False,
                confidence=1.0,
                metadata={"call_type": call_type, "arg_count": arg_count},
            )
        # Descend into func + args to find further Calls / Raises / etc.
        self._visit_value(getattr(node, "func", None))
        self._visit_value(getattr(node, "args", []))

    def _visit_try(self, node: Any) -> None:
        for stmt in getattr(node, "body", []):
            self._visit(stmt)
        for handler in getattr(node, "handlers", []):
            self._visit_except_handler(handler)
        for stmt in getattr(node, "orelse", []):
            self._visit(stmt)
        for stmt in getattr(node, "finalbody", []):
            self._visit(stmt)

    def _visit_except_handler(self, handler: Any) -> None:
        exc_type_node = getattr(handler, "type", None)
        handler_var = getattr(handler, "name", None)

        # Emit one CATCHES edge per type in `except (A, B): ...`, since
        # they're semantically separate catches.
        if exc_type_node is None:
            self._emit_catches(None, handler_var)
        elif getattr(exc_type_node, "kind", None) == "TupleExpr":
            for elem in getattr(exc_type_node, "elements", []):
                name = self._expr_to_name_string(elem)
                self._emit_catches(name, handler_var)
        else:
            name = self._expr_to_name_string(exc_type_node)
            self._emit_catches(name, handler_var)

        for stmt in getattr(handler, "body", []):
            self._visit(stmt)

    def _emit_catches(self, exception_name: Optional[str],
                      handler_var: Optional[str]) -> None:
        if self.current_function is None:
            return
        target = exception_name if exception_name else "bare_except"
        self._add_edge(
            source_id=self.current_function,
            relationship="CATCHES",
            target_id=target,
            is_resolved=False,
            confidence=0.8,
            metadata={
                "exception_name": exception_name or "bare_except",
                "handler_var": handler_var,
            },
        )

    def _visit_raise(self, node: Any) -> None:
        if self.current_function is None:
            # Still recurse for any Call nested inside the raise expr.
            self._visit_value(getattr(node, "exc", None))
            self._visit_value(getattr(node, "cause", None))
            return

        exc = getattr(node, "exc", None)
        if exc is None:
            target_name = None
            raise_type = "re_raise"
        else:
            # `raise SomeError(...)` -> capture the called class.
            if getattr(exc, "kind", None) == "Call":
                target_name = self._expr_to_name_string(getattr(exc, "func", None))
            else:
                target_name = self._expr_to_name_string(exc)
            raise_type = target_name if target_name else "re_raise"

        self._add_edge(
            source_id=self.current_function,
            relationship="RAISES",
            target_id=target_name if target_name else "re_raise",
            is_resolved=False,
            confidence=0.9,
            metadata={"raise_type": raise_type},
        )
        # Recurse into the raised expression so any Call inside it is
        # also recorded (e.g. `raise func()`).
        self._visit_value(getattr(node, "exc", None))
        self._visit_value(getattr(node, "cause", None))

    def _visit_assign(self, node: Any) -> None:
        """Handle both `AssignStatement` and `AnnAssignStatement`. Only
        emits a `variable` node when the target is a simple `Name` and
        we are at module level."""
        is_ann = node.kind == "AnnAssignStatement"

        at_module_level = (
            self.current_class is None and self.current_function is None
        )

        if at_module_level:
            value = getattr(node, "value", None)
            if is_ann:
                target = getattr(node, "target", None)
                if getattr(target, "kind", None) == "Name":
                    self._emit_module_variable(target.id, value, node.line)
            else:
                for target in getattr(node, "targets", []):
                    if getattr(target, "kind", None) == "Name":
                        self._emit_module_variable(target.id, value, node.line)

        # Always recurse into the value (and targets, since they can
        # contain Calls in subscript/attribute positions).
        if is_ann:
            self._visit_value(getattr(node, "target", None))
            self._visit_value(getattr(node, "value", None))
        else:
            for t in getattr(node, "targets", []):
                self._visit_value(t)
            self._visit_value(getattr(node, "value", None))

    def _emit_module_variable(self, name: str, value: Any, line: int) -> None:
        var_id = Node.make_id(self._file_path, "", name)
        var_node = Node(
            id=var_id,
            name=name,
            type="variable",
            file_path=self._file_path,
            line_number=line,
            language="python",
            metadata={"value": self._value_repr(value)},
        )
        self._add_node(var_node)

    # ---- helpers -----------------------------------------------------

    def _extract_call_target(self, call_node: Any) -> tuple:
        """Return (target_name_string, call_type) for a Call.
        call_type is 'method' when the callee is an Attribute, otherwise
        'function'. Returns (None, 'function') if the callee shape is
        not extractable (e.g. a chained Call or Subscript)."""
        func = getattr(call_node, "func", None)
        if func is None:
            return None, "function"
        kind = getattr(func, "kind", None)
        if kind == "Name":
            return func.id, "function"
        if kind == "Attribute":
            return func.attr, "method"
        if kind == "Call":
            inner, _ = self._extract_call_target(func)
            return inner, "function"
        # SubscriptExpr or anything else — keep edge but with no target
        return None, "function"

    def _extract_decorator_name(self, decorator_node: Any) -> Optional[str]:
        """`Decorator.expr` is either a Name, Attribute, or Call (for
        `@deco(args)` form). Return the dotted name being applied."""
        expr = getattr(decorator_node, "expr", decorator_node)
        return self._expr_to_name_string(expr)

    def _expr_to_name_string(self, expr: Any) -> Optional[str]:
        """Render a Name / Attribute / Call expression as a dotted name
        string. Returns None if the shape is not a simple name chain."""
        if expr is None:
            return None
        kind = getattr(expr, "kind", None)
        if kind == "Name":
            return expr.id
        if kind == "Attribute":
            base = self._expr_to_name_string(getattr(expr, "value", None))
            attr = getattr(expr, "attr", "")
            if base is None:
                return attr or None
            return base + "." + attr
        if kind == "Call":
            # e.g. `@cache(maxsize=10)` -> use the function being called.
            return self._expr_to_name_string(getattr(expr, "func", None))
        if kind == "Constant":
            v = getattr(expr, "value", None)
            return str(v) if v is not None else None
        return None

    def _get_docstring(self, body: List[Any]) -> Optional[str]:
        """Extract docstring from the first statement in a body if present."""
        if not body:
            return None
        first = body[0]
        if getattr(first, "kind", None) != "ExprStatement":
            return None
        value = getattr(first, "value", None)
        if getattr(value, "kind", None) != "Constant":
            return None
        if getattr(value, "value_type", None) in ("string", "fstring"):
            raw = value.value
            if not raw:
                return None
            # Strip surrounding quote delimiters
            for quote in ('"""', "'''", '"', "'"):
                if (
                    raw.startswith(quote)
                    and raw.endswith(quote)
                    and len(raw) >= len(quote) * 2
                ):
                    return raw[len(quote):-len(quote)].strip()
            return raw.strip()
        return None

    def _value_repr(self, value: Any) -> str:
        """Cheap string view of an assignment's RHS for variable
        metadata. Constants get their literal printed; anything else is
        collapsed to 'complex'."""
        if value is None:
            return "None"
        if getattr(value, "kind", None) == "Constant":
            return str(value.value)
        return "complex"

    def _module_name_from_path(self, path: str) -> str:
        # Take the last path segment, strip a trailing `.py` if present.
        sep = "/"
        if "\\" in path and "/" not in path:
            sep = "\\"
        base = path.rsplit(sep, 1)[-1] if path else ""
        if base.endswith(".py"):
            base = base[:-3]
        return base or path

    # ---- graph plumbing --------------------------------------------

    def _add_node(self, node: Node) -> None:
        if not self._graph.has_node(node.id):
            self._graph.add_node(node)

    def _emit_decorates_edges(
        self, target_id: str, decorators: List[Optional[str]],
    ) -> None:
        """Emit one unresolved DECORATES edge (decorator -> decorated
        entity) per non-empty decorator name. Shared by the function and
        class visitors."""
        for dec_name in decorators:
            if not dec_name:
                continue
            self._add_edge(
                source_id=dec_name,
                relationship="DECORATES",
                target_id=target_id,
                is_resolved=False,
                confidence=1.0,
                metadata={"decorator_name": dec_name},
            )

    def _add_edge(
        self,
        source_id: str,
        relationship: str,
        target_id: Optional[str],
        is_resolved: bool,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        # `Edge` rejects empty/None ids — coerce to a sentinel string so
        # we never lose the relationship just because its target was a
        # `bare except` or `re-raise`.
        if not source_id:
            return
        if not target_id:
            target_id = "<unknown>"

        base_id = source_id + "--" + relationship + "--" + target_id
        count = self._edge_id_counts.get(base_id, 0)
        edge_id = base_id if count == 0 else base_id + "--" + str(count)
        self._edge_id_counts[base_id] = count + 1

        edge = Edge(
            id=edge_id,
            source_id=source_id,
            target_id=target_id,
            relationship=relationship,
            confidence=confidence,
            is_resolved=is_resolved,
            metadata=metadata or {},
        )
        self._graph.add_edge(edge)
