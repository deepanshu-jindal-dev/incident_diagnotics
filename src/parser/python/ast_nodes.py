"""AST node records produced by `PythonParser`.

Each node is a small dataclass carrying a `kind` discriminator string,
a source `line`, and construct-specific fields. `PythonParser`
constructs them; `Walker` consumes them by reading `.kind` (duck-typed,
no import). They live here, apart from the parser, because the node
*vocabulary* is a single cohesive unit that changes together as the
supported grammar grows.

`ParseError` is included as the parser's error record — it is data, not
logic, and travels with the node definitions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple as Tup


@dataclass
class Module:
    body: List[Any] = field(default_factory=list)
    line: int = 1
    kind: str = "Module"


@dataclass
class FunctionDef:
    name: str = ""
    params: List[Any] = field(default_factory=list)
    body: List[Any] = field(default_factory=list)
    decorators: List[Any] = field(default_factory=list)
    returns: Optional[Any] = None
    line: int = 0
    kind: str = "FunctionDef"


@dataclass
class AsyncFunctionDef:
    name: str = ""
    params: List[Any] = field(default_factory=list)
    body: List[Any] = field(default_factory=list)
    decorators: List[Any] = field(default_factory=list)
    returns: Optional[Any] = None
    line: int = 0
    kind: str = "AsyncFunctionDef"


@dataclass
class ClassDef:
    name: str = ""
    bases: List[Any] = field(default_factory=list)
    keywords: List[Any] = field(default_factory=list)
    body: List[Any] = field(default_factory=list)
    decorators: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "ClassDef"


@dataclass
class ImportStatement:
    names: List[Tup[str, Optional[str]]] = field(default_factory=list)
    line: int = 0
    kind: str = "ImportStatement"


@dataclass
class ImportFromStatement:
    module: Optional[str] = None
    names: List[Tup[str, Optional[str]]] = field(default_factory=list)
    level: int = 0
    line: int = 0
    kind: str = "ImportFromStatement"


@dataclass
class Decorator:
    expr: Any = None
    line: int = 0
    kind: str = "Decorator"


@dataclass
class Parameter:
    name: str = ""
    annotation: Optional[Any] = None
    default: Optional[Any] = None
    # One of: "pos", "posonly", "kwonly", "vararg" (*args), "kwarg" (**kw)
    kind_marker: str = "pos"
    line: int = 0
    kind: str = "Parameter"


@dataclass
class Argument:
    value: Any = None
    name: Optional[str] = None
    is_star: bool = False
    is_double_star: bool = False
    line: int = 0
    kind: str = "Argument"


@dataclass
class Call:
    func: Any = None
    args: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "Call"


@dataclass
class Attribute:
    value: Any = None
    attr: str = ""
    line: int = 0
    kind: str = "Attribute"


@dataclass
class Name:
    id: str = ""
    line: int = 0
    kind: str = "Name"


@dataclass
class Constant:
    value: Any = None
    # "number", "string", "fstring", "bytes", "none", "bool", "ellipsis"
    value_type: str = ""
    line: int = 0
    kind: str = "Constant"


@dataclass
class BinaryOp:
    op: str = ""
    left: Any = None
    right: Any = None
    line: int = 0
    kind: str = "BinaryOp"


@dataclass
class UnaryOp:
    op: str = ""
    operand: Any = None
    line: int = 0
    kind: str = "UnaryOp"


@dataclass
class BoolOp:
    op: str = ""
    values: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "BoolOp"


@dataclass
class Compare:
    left: Any = None
    ops: List[str] = field(default_factory=list)
    comparators: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "Compare"


@dataclass
class IfStatement:
    test: Any = None
    body: List[Any] = field(default_factory=list)
    orelse: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "IfStatement"


@dataclass
class WhileLoop:
    test: Any = None
    body: List[Any] = field(default_factory=list)
    orelse: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "WhileLoop"


@dataclass
class ForLoop:
    target: Any = None
    iter: Any = None
    body: List[Any] = field(default_factory=list)
    orelse: List[Any] = field(default_factory=list)
    is_async: bool = False
    line: int = 0
    kind: str = "ForLoop"


@dataclass
class TryStatement:
    body: List[Any] = field(default_factory=list)
    handlers: List[Any] = field(default_factory=list)
    orelse: List[Any] = field(default_factory=list)
    finalbody: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "TryStatement"


@dataclass
class ExceptHandler:
    type: Optional[Any] = None
    name: Optional[str] = None
    body: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "ExceptHandler"


@dataclass
class WithStatement:
    items: List[Tup[Any, Any]] = field(default_factory=list)
    body: List[Any] = field(default_factory=list)
    is_async: bool = False
    line: int = 0
    kind: str = "WithStatement"


@dataclass
class ReturnStatement:
    value: Optional[Any] = None
    line: int = 0
    kind: str = "ReturnStatement"


@dataclass
class AssignStatement:
    targets: List[Any] = field(default_factory=list)
    value: Any = None
    line: int = 0
    kind: str = "AssignStatement"


@dataclass
class AugAssignStatement:
    target: Any = None
    op: str = ""
    value: Any = None
    line: int = 0
    kind: str = "AugAssignStatement"


@dataclass
class AnnAssignStatement:
    target: Any = None
    annotation: Any = None
    value: Optional[Any] = None
    line: int = 0
    kind: str = "AnnAssignStatement"


@dataclass
class GlobalStatement:
    names: List[str] = field(default_factory=list)
    line: int = 0
    kind: str = "GlobalStatement"


@dataclass
class NonlocalStatement:
    names: List[str] = field(default_factory=list)
    line: int = 0
    kind: str = "NonlocalStatement"


@dataclass
class DeleteStatement:
    targets: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "DeleteStatement"


@dataclass
class AssertStatement:
    test: Any = None
    msg: Optional[Any] = None
    line: int = 0
    kind: str = "AssertStatement"


@dataclass
class RaiseStatement:
    exc: Optional[Any] = None
    cause: Optional[Any] = None
    line: int = 0
    kind: str = "RaiseStatement"


@dataclass
class PassStatement:
    line: int = 0
    kind: str = "PassStatement"


@dataclass
class BreakStatement:
    line: int = 0
    kind: str = "BreakStatement"


@dataclass
class ContinueStatement:
    line: int = 0
    kind: str = "ContinueStatement"


@dataclass
class YieldStatement:
    value: Optional[Any] = None
    is_from: bool = False
    line: int = 0
    kind: str = "YieldStatement"


@dataclass
class Lambda:
    params: List[Any] = field(default_factory=list)
    body: Any = None
    line: int = 0
    kind: str = "Lambda"


@dataclass
class Comprehension:
    # "list", "set", "dict", "gen"
    comprehension_kind: str = "list"
    elt: Any = None
    key: Optional[Any] = None
    value: Optional[Any] = None
    generators: List[Dict[str, Any]] = field(default_factory=list)
    line: int = 0
    kind: str = "Comprehension"


@dataclass
class SubscriptExpr:
    value: Any = None
    slice: Any = None
    line: int = 0
    kind: str = "SubscriptExpr"


@dataclass
class StarredExpr:
    value: Any = None
    is_double: bool = False
    line: int = 0
    kind: str = "StarredExpr"


@dataclass
class IfExpr:
    test: Any = None
    body: Any = None
    orelse: Any = None
    line: int = 0
    kind: str = "IfExpr"


@dataclass
class WalrusExpr:
    target: Any = None
    value: Any = None
    line: int = 0
    kind: str = "WalrusExpr"


@dataclass
class MatchStatement:
    subject: Any = None
    cases: List[Dict[str, Any]] = field(default_factory=list)
    line: int = 0
    kind: str = "MatchStatement"


# ---- additional helper node types -----------------------------------
# Tuple/list/dict/set literals, await, slice, expression statement, and
# an error sentinel. Not listed explicitly in the task spec, but every
# requested *construct* (e.g. "List, dict, set, tuple literals", "Await
# expressions") needs a representation in the tree.


@dataclass
class TupleExpr:
    elements: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "TupleExpr"


@dataclass
class ListExpr:
    elements: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "ListExpr"


@dataclass
class DictExpr:
    keys: List[Any] = field(default_factory=list)  # None entries = **unpack
    values: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "DictExpr"


@dataclass
class SetExpr:
    elements: List[Any] = field(default_factory=list)
    line: int = 0
    kind: str = "SetExpr"


@dataclass
class Await:
    value: Any = None
    line: int = 0
    kind: str = "Await"


@dataclass
class Slice:
    lower: Optional[Any] = None
    upper: Optional[Any] = None
    step: Optional[Any] = None
    line: int = 0
    kind: str = "Slice"


@dataclass
class ExprStatement:
    value: Any = None
    line: int = 0
    kind: str = "ExprStatement"


@dataclass
class ErrorNode:
    message: str = ""
    line: int = 0
    kind: str = "ErrorNode"


@dataclass
class ParseError:
    message: str = ""
    line: int = 0
    column: int = 0


__all__ = [
    "Module",
    "FunctionDef",
    "AsyncFunctionDef",
    "ClassDef",
    "ImportStatement",
    "ImportFromStatement",
    "Decorator",
    "Parameter",
    "Argument",
    "Call",
    "Attribute",
    "Name",
    "Constant",
    "BinaryOp",
    "UnaryOp",
    "BoolOp",
    "Compare",
    "IfStatement",
    "WhileLoop",
    "ForLoop",
    "TryStatement",
    "ExceptHandler",
    "WithStatement",
    "ReturnStatement",
    "AssignStatement",
    "AugAssignStatement",
    "AnnAssignStatement",
    "GlobalStatement",
    "NonlocalStatement",
    "DeleteStatement",
    "AssertStatement",
    "RaiseStatement",
    "PassStatement",
    "BreakStatement",
    "ContinueStatement",
    "YieldStatement",
    "Lambda",
    "Comprehension",
    "SubscriptExpr",
    "StarredExpr",
    "IfExpr",
    "WalrusExpr",
    "MatchStatement",
    "TupleExpr",
    "ListExpr",
    "DictExpr",
    "SetExpr",
    "Await",
    "Slice",
    "ExprStatement",
    "ErrorNode",
    "ParseError",
]
