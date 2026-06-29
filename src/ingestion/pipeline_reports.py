"""Report dataclasses produced by the ingestion pipeline.

These are plain data records carrying the outcome of a per-file
processing step (`_ProcessResult`), a storage write (`StorageInfo`), a
single-repo run (`PipelineReport`), or a multi-repo run
(`MultiPipelineReport`). They hold no logic — the pipeline populates
them and callers read them.
"""

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

# Make `src/` importable so `graph.graph.Graph` resolves regardless of
# how this module is first imported.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_HERE)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from graph.graph import Graph  # noqa: E402


@dataclass
class _ProcessResult:
    """Carries the outcome of one file-processing strategy call."""
    graph: Optional[Graph] = None
    errors: List[str] = field(default_factory=list)
    failed_files: List[str] = field(default_factory=list)


@dataclass
class StorageInfo:
    json_path: str = ""
    pickle_path: str = ""
    node_count: int = 0
    edge_count: int = 0


@dataclass
class PipelineReport:
    repo_path: str = ""
    total_files_discovered: int = 0
    files_processed_successfully: int = 0
    files_failed: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    resolution_rate: float = 0.0
    output_json_path: str = ""
    output_pickle_path: str = ""
    failed_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class MultiPipelineReport:
    repo_paths: List[str] = field(default_factory=list)
    individual_reports: List[PipelineReport] = field(default_factory=list)
    total_files_discovered: int = 0
    total_files_processed: int = 0
    total_nodes: int = 0
    total_edges: int = 0
    resolution_rate: float = 0.0
    output_json_path: str = ""
    output_pickle_path: str = ""
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)
