"""Static analysis of a target repository (ADR-0006): modules, symbols, changes, imports, blast."""

from repro.analysis.blast import BlastRadius, blast_radius, graph_payloads
from repro.analysis.changes import (
    ChangedSymbols,
    SymbolChange,
    Unanalysed,
    changed_symbols,
    changed_symbols_between,
)
from repro.analysis.imports import GraphProblem, ImportGraph, import_graph
from repro.analysis.modules import module_names
from repro.analysis.static import StaticAnalysis, analyse
from repro.analysis.symbols import Symbol, SymbolTable, build_table

__all__ = [
    "BlastRadius",
    "ChangedSymbols",
    "GraphProblem",
    "ImportGraph",
    "StaticAnalysis",
    "Symbol",
    "SymbolChange",
    "SymbolTable",
    "Unanalysed",
    "analyse",
    "blast_radius",
    "build_table",
    "changed_symbols",
    "changed_symbols_between",
    "graph_payloads",
    "import_graph",
    "module_names",
]
