"""Catalog of Python builtin / stdlib names used by entity resolution.

This module holds only *reference data* — the frozen sets of names that
the `EntityResolver` consults to decide whether an unresolved symbol is
a project entity worth flagging or a language/stdlib primitive that
should simply be tagged `is_builtin`. It contains no logic; the
resolver imports these sets and applies them.
"""

import builtins as _builtins


# Built-in Python exceptions that should never be expected to appear
# as nodes in a project graph.
BUILTIN_EXCEPTIONS = frozenset({
    "Exception", "BaseException",
    "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "ImportError", "OSError", "IOError",
    "RuntimeError", "StopIteration", "GeneratorExit",
    "SystemExit", "KeyboardInterrupt", "NotImplementedError",
    "OverflowError", "ZeroDivisionError", "MemoryError",
    "RecursionError", "TimeoutError", "ConnectionError",
    "FileNotFoundError", "PermissionError", "IsADirectoryError",
})


# Common stdlib *base classes* — used to tag `EXTENDS` edges whose
# parent is a stdlib type rather than a project class.
BUILTIN_BASE_CLASSES = frozenset({
    "object", "type",
    "str", "bytes", "bytearray", "memoryview",
    "int", "float", "complex", "bool",
    "list", "tuple", "dict", "set", "frozenset",
    # enums
    "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "auto",
    "enum.Enum", "enum.IntEnum", "enum.StrEnum",
    "enum.Flag", "enum.IntFlag",
    # typing
    "NamedTuple", "TypedDict", "Protocol", "Generic",
    "typing.NamedTuple", "typing.TypedDict",
    "typing.Protocol", "typing.Generic",
    # collections
    "OrderedDict", "defaultdict", "Counter", "deque", "ChainMap",
    "UserDict", "UserList", "UserString",
    "collections.OrderedDict", "collections.defaultdict",
    "collections.Counter", "collections.deque", "collections.ChainMap",
    # abc
    "ABC", "ABCMeta", "abc.ABC", "abc.ABCMeta",
    # threading / context
    "Thread", "Lock",
})


# Decorators that come from the stdlib / language itself rather than
# from any project file.
BUILTIN_DECORATORS = frozenset({
    "property", "staticmethod", "classmethod",
    "abstractmethod", "abstractproperty",
    "abstractclassmethod", "abstractstaticmethod",
    "abc.abstractmethod", "abc.abstractproperty",
    "dataclass", "dataclasses.dataclass",
    "contextmanager", "asynccontextmanager",
    "contextlib.contextmanager", "contextlib.asynccontextmanager",
    "wraps", "functools.wraps",
    "lru_cache", "functools.lru_cache",
    "cache", "functools.cache",
    "cached_property", "functools.cached_property",
    "singledispatch", "functools.singledispatch",
    "singledispatchmethod", "functools.singledispatchmethod",
    "partial", "functools.partial",
    "total_ordering", "functools.total_ordering",
    "overload", "typing.overload",
    "final", "typing.final",
    "no_type_check", "typing.no_type_check",
    "runtime_checkable", "typing.runtime_checkable",
})


# Dict / list / str / set / file methods. The walker emits a CALLS
# edge for `obj.foo()` with target = "foo", which is indistinguishable
# from a real function call at walk time. We can't tell from the name
# alone whether `append` is `list.append` or a project function, so
# this is a heuristic: if the name matches a built-in method we tag
# it as builtin rather than flagging it as a project miss.
BUILTIN_METHODS = frozenset({
    # list
    "append", "extend", "insert", "remove", "pop", "clear",
    "sort", "reverse", "copy", "index", "count",
    # dict
    "keys", "values", "items", "get", "update", "setdefault",
    "popitem", "fromkeys",
    # str
    "split", "rsplit", "splitlines", "join", "strip", "lstrip", "rstrip",
    "replace", "format", "format_map", "encode", "decode",
    "lower", "upper", "title", "capitalize", "swapcase", "casefold",
    "startswith", "endswith", "find", "rfind", "rindex",
    "isalpha", "isdigit", "isalnum", "isspace", "islower", "isupper",
    "istitle", "isidentifier", "isnumeric", "isdecimal", "isascii",
    "isprintable",
    "ljust", "rjust", "center", "zfill",
    "translate", "maketrans", "expandtabs",
    "partition", "rpartition", "removeprefix", "removesuffix",
    # set
    "add", "discard", "union", "intersection", "difference",
    "symmetric_difference", "issubset", "issuperset", "isdisjoint",
    "intersection_update", "difference_update",
    "symmetric_difference_update",
    # bytes
    "hex", "fromhex",
    # file I/O
    "read", "readline", "readlines", "write", "writelines",
    "seek", "tell", "flush", "close", "readable", "writable", "seekable",
    # iterators / generators
    "send", "throw",
    # re.Match
    "group", "groups", "groupdict", "span", "start", "end",
    # threading / locks
    "acquire", "release", "wait", "notify", "notify_all",
    "is_alive",
    # pathlib.Path
    "exists", "is_file", "is_dir", "is_symlink", "resolve",
    "absolute", "relative_to", "with_suffix", "with_name",
    "with_stem", "as_posix", "as_uri",
})


# Every name in `builtins`, minus those we already classify elsewhere.
# Built lazily from the interpreter so we automatically pick up new
# names without having to maintain a hand-coded list.
BUILTIN_FUNCTIONS = frozenset(
    name for name in dir(_builtins)
    if not name.startswith("_")
    and callable(getattr(_builtins, name, None))
) - BUILTIN_EXCEPTIONS - BUILTIN_BASE_CLASSES


# Stdlib top-level modules: when we see `os.path.join` as a call
# target we want to recognize it as stdlib even though we can't grep
# every member of every stdlib module.
KNOWN_STDLIB_MODULES = frozenset({
    "os", "sys", "re", "json", "math", "time", "datetime",
    "argparse", "collections", "itertools", "functools",
    "typing", "pathlib", "io", "abc", "copy", "enum",
    "uuid", "hashlib", "warnings", "logging", "asyncio",
    "threading", "subprocess", "shutil", "tempfile", "pickle",
    "urllib", "http", "socket", "ssl", "csv", "string",
    "textwrap", "importlib", "importlib_metadata", "contextlib",
    "weakref", "operator", "random", "statistics", "decimal",
    "platform", "traceback", "inspect", "ast", "tokenize",
    "dataclasses", "types",
})
