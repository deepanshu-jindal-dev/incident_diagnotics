"""Entity resolution for the code knowledge graph.

After the walker runs, many edges are placeholders: their `target_id`
(or, for DECORATES, their `source_id`) is just the raw symbol name the
walker saw in source — `"charge"`, `"PaymentService"`,
`"payments::PaymentService"` — and `is_resolved` is False.

This module rewrites those placeholders to real node ids using four
layered strategies (same-file, symbol table, name index, partial id
match). It never modifies a node, never mutates an edge's id, and
swallows every per-edge failure into a `ResolutionReport.errors` list
so one bad edge cannot derail the pass.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from graph.edge import Edge
from graph.graph import Graph
from graph.node import Node
from resolution.builtins_catalog import (
    BUILTIN_BASE_CLASSES,
    BUILTIN_DECORATORS,
    BUILTIN_EXCEPTIONS,
    BUILTIN_FUNCTIONS,
    BUILTIN_METHODS,
    KNOWN_STDLIB_MODULES,
)


# Ranking used when Strategy 3 has multiple candidates of different
# types — functions are preferred over classes per spec.
_TYPE_RANK = {"function": 0, "class": 1, "module": 2, "variable": 3}


@dataclass
class ResolutionReport:
    total_edges: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    skipped_count: int = 0      # CONTAINS edges, never touched
    builtin_count: int = 0      # edges tagged is_builtin (stdlib/builtin)
    imports_count: int = 0      # IMPORTS edges, out of resolver scope
    resolution_rate: float = 0.0
    unresolved_edges: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class EntityResolver:
    """Walks every unresolved edge in a populated `Graph` and rewrites
    its endpoints to real node ids.

    The resolver is stateless across calls but builds per-graph
    indexes (symbol table, name index) once at the start of `resolve`
    so each edge lookup is O(1) on average.
    """

    BUILTIN_EXCEPTIONS = BUILTIN_EXCEPTIONS

    # --- main entry point --------------------------------------------

    def resolve(self, graph: Graph) -> ResolutionReport:
        report = ResolutionReport()
        report.total_edges = graph.edge_count

        symbol_table: Dict[str, Dict[str, str]] = {}
        name_index: Dict[str, List[str]] = {}
        file_name_index: Dict[Tuple[str, str], str] = {}

        try:
            symbol_table = self._build_symbol_table(graph)
        except Exception as ex:
            report.errors.append("symbol-table build failed: " + repr(ex))

        try:
            name_index, file_name_index = self._build_name_index(graph)
        except Exception as ex:
            report.errors.append("name-index build failed: " + repr(ex))

        # Resolve each relationship in turn. Each method handles its
        # own per-edge try/except so a failure in one bucket cannot
        # block the others.
        self._resolve_calls(graph, symbol_table, name_index, file_name_index, report)
        self._resolve_extends(graph, symbol_table, name_index, file_name_index, report)
        self._resolve_raises_catches(graph, symbol_table, name_index, file_name_index, report)
        self._resolve_decorates(graph, symbol_table, name_index, file_name_index, report)

        # Tally final state from the graph itself rather than from
        # counters incremented along the way — that way the report
        # reflects the actual graph even if an exception left the
        # counters skewed.
        #
        # Buckets are mutually exclusive:
        #   - CONTAINS              -> skipped_count
        #   - IMPORTS               -> imports_count (out of scope)
        #   - is_builtin tagged     -> builtin_count (stdlib/builtin)
        #   - is_resolved=True      -> resolved_count
        #   - everything else       -> unresolved_count
        #
        # The resolution rate's denominator excludes the first three
        # buckets so we're not penalised for edges that were never
        # resolvable in principle.
        report.resolved_count = 0
        report.unresolved_count = 0
        report.skipped_count = 0
        report.builtin_count = 0
        report.imports_count = 0
        report.unresolved_edges = []
        for edge in graph.all_edges():
            if edge.relationship == "CONTAINS":
                report.skipped_count += 1
                continue
            if edge.relationship == "IMPORTS":
                report.imports_count += 1
                report.unresolved_edges.append(edge.id)
                continue
            if edge.metadata.get("is_builtin"):
                report.builtin_count += 1
                report.unresolved_edges.append(edge.id)
                continue
            if edge.is_resolved:
                report.resolved_count += 1
            else:
                report.unresolved_count += 1
                report.unresolved_edges.append(edge.id)

        eligible = (
            report.total_edges
            - report.skipped_count
            - report.imports_count
            - report.builtin_count
        )
        report.resolution_rate = (
            report.resolved_count / eligible if eligible > 0 else 0.0
        )
        return report

    # --- Step 1: symbol table ----------------------------------------

    def _build_symbol_table(self, graph: Graph) -> Dict[str, Dict[str, str]]:
        """Per-file map from local symbol → resolved node id (or the
        raw target string as a best-guess fallback)."""
        table: Dict[str, Dict[str, str]] = {}
        for edge in graph.all_edges():
            if edge.relationship != "IMPORTS":
                continue
            try:
                file_path = self._extract_file_path(edge.source_id)
                target = edge.target_id or ""
                meta = edge.metadata or {}
                alias = meta.get("alias")

                if "::" in target:
                    _, name_part = target.split("::", 1)
                    local_name = alias if alias else name_part
                else:
                    local_name = alias if alias else target
                if not local_name:
                    continue

                resolved = self._find_import_target_node(graph, target) or target
                table.setdefault(file_path, {})[local_name] = resolved
            except Exception:
                # Symbol-table building must never raise.
                continue
        return table

    def _find_import_target_node(self, graph: Graph, target_id: str) -> Optional[str]:
        """Best-effort lookup of the node referenced by an IMPORTS
        edge target. Tries a `module[::name]`-aware match first (so
        `"payments::PaymentService"` finds `"payments.py::PaymentService::"`),
        then falls back to the spec's plain substring search."""
        if not target_id:
            return None

        if "::" in target_id:
            module_part, name_part = target_id.split("::", 1)
            for node in graph.all_nodes():
                if node.name != name_part:
                    continue
                if self._file_matches_module(node.file_path, module_part):
                    return node.id
        else:
            # Plain `import foo` — only module-type nodes are plausible.
            for node in graph.all_nodes():
                if node.type != "module":
                    continue
                if self._file_matches_module(node.file_path, target_id):
                    return node.id

        # Spec fallback: any node whose id contains target_id verbatim.
        for node in graph.all_nodes():
            if target_id in node.id:
                return node.id
        return None

    def _file_matches_module(self, file_path: str, module_part: str) -> bool:
        if not file_path or not module_part:
            return False
        base = file_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        stem = base.rsplit(".", 1)[0] if "." in base else base
        # Match against the bare stem, or against any path segment so
        # `from pkg.sub import x` finds `pkg/sub.py`.
        if stem == module_part:
            return True
        normalized = file_path.replace("\\", "/")
        return ("/" + module_part + "/") in normalized or normalized.endswith("/" + module_part + ".py")

    # --- Step 2: name indexes ----------------------------------------

    def _build_name_index(self, graph: Graph) -> Tuple[Dict[str, List[str]], Dict[Tuple[str, str], str]]:
        name_index: Dict[str, List[str]] = {}
        file_name_index: Dict[Tuple[str, str], str] = {}
        for node in graph.all_nodes():
            if not node.name:
                continue
            name_index.setdefault(node.name, []).append(node.id)
            file_name_index[(node.file_path, node.name)] = node.id
        return name_index, file_name_index

    # --- shared per-edge iteration -----------------------------------

    def _for_each_unresolved(
        self,
        graph: Graph,
        relationships: Tuple[str, ...],
        report: ResolutionReport,
        handler,
    ) -> None:
        """Call `handler(edge)` for every unresolved edge whose
        relationship is in `relationships`, wrapping each call so one
        bad edge records an error instead of aborting the whole bucket.
        """
        for edge in graph.all_edges():
            if edge.relationship not in relationships or edge.is_resolved:
                continue
            try:
                handler(edge)
            except Exception as ex:
                report.errors.append(
                    edge.relationship + " edge " + edge.id + ": " + repr(ex)
                )

    # --- Step 3a: CALLS ---------------------------------------------

    def _resolve_calls(
        self,
        graph: Graph,
        symbol_table: Dict[str, Dict[str, str]],
        name_index: Dict[str, List[str]],
        file_name_index: Dict[Tuple[str, str], str],
        report: ResolutionReport,
    ) -> None:
        def handle(edge: Edge) -> None:
            target_name = edge.target_id
            source_file = self._extract_file_path(edge.source_id)
            resolved = self._find_node_for_name(
                graph, target_name, source_file,
                symbol_table, name_index, file_name_index,
            )
            if resolved:
                self._mark_resolved(graph, edge, resolved)
                return
            # Not in graph — see if the name is a known builtin
            # method or stdlib function before declaring it a miss.
            kind = self._call_builtin_kind(target_name)
            if kind is not None:
                self._tag_builtin(graph, edge, kind)
                return
            self._mark_unresolved(
                graph, edge, reason="call target not found in graph",
            )

        self._for_each_unresolved(graph, ("CALLS",), report, handle)

    # --- Step 3b: EXTENDS -------------------------------------------

    def _resolve_extends(
        self,
        graph: Graph,
        symbol_table: Dict[str, Dict[str, str]],
        name_index: Dict[str, List[str]],
        file_name_index: Dict[Tuple[str, str], str],
        report: ResolutionReport,
    ) -> None:
        def handle(edge: Edge) -> None:
            target_name = edge.target_id
            source_file = self._extract_file_path(edge.source_id)
            resolved = self._find_node_for_name(
                graph, target_name, source_file,
                symbol_table, name_index, file_name_index,
                preferred_type="class",
            )
            if resolved:
                self._mark_resolved(graph, edge, resolved)
                return
            # Built-in base classes (Enum, NamedTuple, str, ...) —
            # tag rather than flag.
            if self._is_builtin_base_class(target_name):
                self._tag_builtin(graph, edge, "base_class")
                return
            # Built-in exceptions used as a base: `class Foo(ValueError)`.
            if self._is_builtin_exception(target_name):
                self._tag_builtin(graph, edge, "exception_base")
                return
            self._mark_unresolved(
                graph, edge, reason="base class not found in graph",
            )

        self._for_each_unresolved(graph, ("EXTENDS",), report, handle)

    # --- Step 3c: RAISES & CATCHES ----------------------------------

    def _resolve_raises_catches(
        self,
        graph: Graph,
        symbol_table: Dict[str, Dict[str, str]],
        name_index: Dict[str, List[str]],
        file_name_index: Dict[Tuple[str, str], str],
        report: ResolutionReport,
    ) -> None:
        def handle(edge: Edge) -> None:
            target_name = edge.target_id
            # Sentinel placeholders the walker emits for bare/empty
            # forms aren't worth resolving — drop confidence and tag.
            if target_name in ("bare_except", "re_raise", "<unknown>"):
                self._mark_unresolved(
                    graph, edge,
                    reason="placeholder target (" + target_name + ")",
                )
                return
            # Built-in exceptions: never expected in graph.
            if self._is_builtin_exception(target_name):
                self._tag_builtin(graph, edge, "exception")
                return

            source_file = self._extract_file_path(edge.source_id)
            resolved = self._find_node_for_name(
                graph, target_name, source_file,
                symbol_table, name_index, file_name_index,
                preferred_type="class",
            )
            if resolved:
                self._mark_resolved(graph, edge, resolved)
            else:
                self._mark_unresolved(
                    graph, edge, reason="exception class not found in graph",
                )

        self._for_each_unresolved(graph, ("RAISES", "CATCHES"), report, handle)

    # --- Step 3d: DECORATES -----------------------------------------

    def _resolve_decorates(
        self,
        graph: Graph,
        symbol_table: Dict[str, Dict[str, str]],
        name_index: Dict[str, List[str]],
        file_name_index: Dict[Tuple[str, str], str],
        report: ResolutionReport,
    ) -> None:
        def handle(edge: Edge) -> None:
            decorator_name = edge.source_id
            # Cheap check first: stdlib decorators (`@property`,
            # `@staticmethod`, `@dataclass`, `@functools.wraps`, ...).
            if self._is_builtin_decorator(decorator_name):
                self._tag_builtin(graph, edge, "decorator")
                return
            # Property descriptors (`@x.setter`, `@x.getter`,
            # `@x.deleter`) — the `x` half points at a project node
            # but the .setter/.getter/.deleter form is a language
            # primitive, not a project decorator.
            if "." in decorator_name and decorator_name.rsplit(".", 1)[-1] in (
                "setter", "getter", "deleter",
            ):
                self._tag_builtin(graph, edge, "property_descriptor")
                return
            # For DECORATES the context-file lives on the target,
            # because the target is the decorated entity which is a
            # real node id and therefore has a file path.
            context_file = self._extract_file_path(edge.target_id)
            resolved = self._find_node_for_name(
                graph, decorator_name, context_file,
                symbol_table, name_index, file_name_index,
                preferred_type="function",
            )
            if resolved:
                self._mark_resolved(graph, edge, resolved, source=True)
            else:
                self._mark_unresolved(
                    graph, edge, reason="decorator not found in graph",
                )

        self._for_each_unresolved(graph, ("DECORATES",), report, handle)

    # --- shared lookup ------------------------------------------------

    def _find_node_for_name(
        self,
        graph: Graph,
        name: str,
        source_file: str,
        symbol_table: Dict[str, Dict[str, str]],
        name_index: Dict[str, List[str]],
        file_name_index: Dict[Tuple[str, str], str],
        preferred_type: Optional[str] = None,
    ) -> Optional[str]:
        """Run the four-strategy lookup. Returns a node id or None."""
        if not name:
            return None

        # ---- Strategy 1 — same-file lookup
        key = (source_file, name)
        if key in file_name_index:
            return file_name_index[key]

        # ---- Strategy 2 — symbol table
        file_table = symbol_table.get(source_file, {})
        if name in file_table:
            candidate = file_table[name]
            if candidate and graph.has_node(candidate):
                return candidate

        # ---- Strategy 3 — global name index
        candidates = list(name_index.get(name, []))
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            # Narrow to candidates whose file appears in this file's
            # symbol table (imported modules) — a strong hint when the
            # source actually imported one of these.
            symbol_files = set()
            for resolved_id in file_table.values():
                f = self._extract_file_path(resolved_id)
                if f:
                    symbol_files.add(f)
            narrowed = [c for c in candidates
                        if self._extract_file_path(c) in symbol_files]
            if len(narrowed) == 1:
                return narrowed[0]
            pool = narrowed if narrowed else candidates

            # Prefer the requested type when given.
            if preferred_type:
                typed = [c for c in pool
                         if self._node_type(graph, c) == preferred_type]
                if typed:
                    pool = typed

            # Final tiebreaker: rank by type (function < class < module
            # < variable) then by descending confidence on the candidate.
            def rank(node_id: str) -> Tuple[int, float]:
                n = graph.get_node(node_id)
                if n is None:
                    return (99, 0.0)
                return (_TYPE_RANK.get(n.type, 4), -float(n.confidence))

            pool_sorted = sorted(pool, key=rank)
            if pool_sorted:
                return pool_sorted[0]

        # ---- Strategy 4 — partial id match
        suffix = "::" + name
        middle = "::" + name + "::"
        matches: List[str] = []
        for node in graph.all_nodes():
            if node.id.endswith(suffix) or middle in node.id:
                matches.append(node.id)
        if len(matches) == 1:
            return matches[0]

        return None

    def _node_type(self, graph: Graph, node_id: str) -> Optional[str]:
        n = graph.get_node(node_id)
        return n.type if n else None

    # --- edge mutation -----------------------------------------------

    def _mark_resolved(
        self, graph: Graph, edge: Edge, resolved_id: str, source: bool = False,
    ) -> None:
        """Mark `edge` resolved, keeping its confidence. By default the
        resolved id becomes the new target; for DECORATES (`source=True`)
        it becomes the new source instead, since the decorator name lives
        on the source side."""
        if source:
            self._replace_edge(
                graph, edge,
                new_target_id=edge.target_id,
                new_confidence=edge.confidence,
                extra_metadata={},
                new_source_id=resolved_id,
                new_is_resolved=True,
            )
        else:
            self._replace_edge(
                graph, edge,
                new_target_id=resolved_id,
                new_confidence=edge.confidence,
                extra_metadata={},
                new_is_resolved=True,
            )

    def _tag_builtin(self, graph: Graph, edge: Edge, kind: str) -> None:
        """Tag `edge` as pointing at a language/stdlib primitive: knock
        confidence down to 0.5, record `builtin_kind`, leave unresolved."""
        self._replace_edge(
            graph, edge,
            new_target_id=edge.target_id,
            new_confidence=0.5,
            extra_metadata={"is_builtin": True, "builtin_kind": kind},
            new_is_resolved=False,
        )

    def _replace_edge(
        self,
        graph: Graph,
        old_edge: Edge,
        new_target_id: str,
        new_confidence: float,
        extra_metadata: Optional[Dict[str, Any]],
        new_source_id: Optional[str] = None,
        new_is_resolved: bool = True,
    ) -> None:
        """Remove `old_edge` and re-insert a new Edge under the same
        id with updated fields. Must touch the graph's adjacency
        indexes so iteration stays consistent."""
        # Remove from the graph's internal stores. `Graph` does not
        # expose a remove API, so we poke its private dicts directly.
        try:
            del graph._edges[old_edge.id]
        except KeyError:
            return
        outgoing_set = graph._outgoing.get(old_edge.source_id)
        if outgoing_set is not None:
            outgoing_set.discard(old_edge.id)
        incoming_set = graph._incoming.get(old_edge.target_id)
        if incoming_set is not None:
            incoming_set.discard(old_edge.id)

        merged_metadata = dict(old_edge.metadata or {})
        if extra_metadata:
            merged_metadata.update(extra_metadata)

        new_edge = Edge(
            id=old_edge.id,
            source_id=new_source_id if new_source_id is not None else old_edge.source_id,
            target_id=new_target_id if new_target_id else old_edge.target_id,
            relationship=old_edge.relationship,
            confidence=float(new_confidence),
            is_resolved=bool(new_is_resolved),
            metadata=merged_metadata,
        )
        graph.add_edge(new_edge)

    def _mark_unresolved(self, graph: Graph, edge: Edge, reason: str) -> None:
        """Edge stays unresolved but the confidence is knocked down by
        0.3 (clamped to [0, 1]) and the reason is recorded."""
        new_conf = max(0.0, min(1.0, edge.confidence - 0.3))
        self._replace_edge(
            graph, edge,
            new_target_id=edge.target_id,
            new_confidence=new_conf,
            extra_metadata={"unresolved_reason": reason},
            new_is_resolved=False,
        )

    # --- utilities ----------------------------------------------------

    def _extract_file_path(self, node_id: str) -> str:
        if not node_id:
            return ""
        idx = node_id.find("::")
        if idx == -1:
            return node_id
        return node_id[:idx]

    def _is_builtin_exception(self, name: str) -> bool:
        return name in BUILTIN_EXCEPTIONS

    def _is_builtin_base_class(self, name: str) -> bool:
        return name in BUILTIN_BASE_CLASSES

    def _is_builtin_decorator(self, name: str) -> bool:
        if name in BUILTIN_DECORATORS:
            return True
        # `@functools.wraps` and similar appear in BUILTIN_DECORATORS
        # already; this catches additional dotted forms like
        # `@some_module.partial` whose head is a known stdlib module.
        if "." in name:
            head = name.split(".", 1)[0]
            if head in KNOWN_STDLIB_MODULES:
                return True
        return False

    def _call_builtin_kind(self, name: str) -> Optional[str]:
        """Classify a CALLS target that wasn't found in the graph.
        Returns 'method' / 'function' / 'stdlib' when the name is a
        known builtin, None when it's plausibly a real project miss."""
        if not name:
            return None
        if name in BUILTIN_METHODS:
            return "method"
        if name in BUILTIN_FUNCTIONS:
            return "function"
        if name in BUILTIN_BASE_CLASSES:
            # `dict(...)`, `list(...)`, `Enum(...)` — calls to a type.
            return "type_call"
        if name in BUILTIN_EXCEPTIONS:
            return "exception_call"
        if "." in name:
            head = name.split(".", 1)[0]
            if head in KNOWN_STDLIB_MODULES:
                return "stdlib"
        return None
