"""Static analysis of a target repository (ADR-0006): modules, symbols, changed symbols."""

from repro.analysis.changes import (
    ChangedSymbols,
    SymbolChange,
    Unanalysed,
    changed_symbols,
    changed_symbols_between,
)
from repro.analysis.modules import module_names
from repro.analysis.symbols import Symbol, SymbolTable, build_table

__all__ = [
    "ChangedSymbols",
    "Symbol",
    "SymbolChange",
    "SymbolTable",
    "Unanalysed",
    "build_table",
    "changed_symbols",
    "changed_symbols_between",
    "module_names",
]
