"""The public API's breaking changes from base to head (E05; ADR-0006, ARCHITECTURE §4.5).

**What the API is.** The project's packages: each directory at an import root that holds an
``__init__.py`` (``repro.analysis.modules``), except test packages (``tests``, ``test``,
``testing``). Their public objects are griffe's: names without a leading underscore, or listed
in ``__all__``.

**How it is read.** griffe (the ``griffelib`` distribution) parses both sides' files statically
with ``allow_inspection=False``: no module of the target is imported, so none of its code runs
on the host (THREAT_MODEL T15). The files come from git, like the rest of the static analysis,
and are written to a scratch tree per side laid out by module name.

**What is compared.** ``griffe.find_breaking_changes`` (removed or moved parameters, changed
defaults and kinds, newly required parameters, removed objects and base classes, changed
attribute values, a return annotation removed). griffe 2.3.2 does not compare annotations
(``_returns_are_compatible`` ends in a TODO that answers compatible; attributes are not
checked), so Repro adds its own text comparison: a public function's return annotation, or an
attribute's annotation, that is present on both sides and reads differently. That is a change
of the declared type, not a proof of incompatibility (``int`` to ``int | None`` is flagged).

The explanations are Repro's own, from the breakage's kind and values: griffe's ``explain()``
names the scratch tree's absolute paths and colours its text for a terminal.
"""

import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

import griffe

from repro import __version__
from repro.analysis.modules import module_names
from repro.gitops import Git, read_blobs, regular_files
from repro.ids import new_evidence_id

#: Top-level packages that hold tests, not API.
TEST_PACKAGES: Final = frozenset({"tests", "test", "testing"})
MODULE_QUALNAME: Final = "<module>"
EXPLANATION: Final = 1000
_VALUE: Final = 200

#: What found a break: griffe, Repro's annotation comparison, or (K11) the TypeScript compiler
#: API, for a JavaScript or TypeScript package (``repro.analysis.jsapi``).
Source = Literal["griffe", "annotations", "typescript"]
_COMPONENTS: Final[dict[str, str]] = {
    "griffe": "repro.analysis.api",
    "annotations": "repro.analysis.api",
    "typescript": "repro.analysis.jsapi",
}


@dataclass(frozen=True, slots=True)
class ApiBreak:
    """One breaking change of the public API."""

    symbol: str  # module:qualname#0
    file: str | None  # the repository path of its module (head's, else base's)
    breakage: str  # the diff.api enum: griffe's BreakageKind, lower case
    explanation: str
    old: str | None
    new: str | None
    source: Source

    def evidence(self, run_id: str) -> dict[str, Any]:
        """The ``api_diff`` evidence record (the writer adds ``seq``)."""
        target: dict[str, str] = {"symbol": self.symbol}
        if self.file is not None:
            target["file"] = self.file
        return {
            "id": new_evidence_id(),
            "run_id": run_id,
            "type": "api_diff",
            "targets": [target],
            "summary": self.explanation,
            "data": {
                "breakage": self.breakage,
                "old": self.old,
                "new": self.new,
                "source": self.source,
            },
            "artifacts": [],
            "stability": "stable",  # read from the sources: the same every run
            "origin": "introduced",
            "produced_by": {"component": _COMPONENTS[self.source], "version": __version__},
        }

    def payload(self, evidence_id: str) -> dict[str, Any]:
        """The ``diff.api`` payload."""
        return {
            "evidence_id": evidence_id,
            "symbol_id": self.symbol,
            "breakage": self.breakage,
            "explanation": self.explanation,
        }


@dataclass
class ApiDiff:
    breaks: list[ApiBreak] = field(default_factory=list)
    #: Packages whose API could not be read on a side, with the reason.
    problems: list[tuple[str, str, str]] = field(default_factory=list)  # side, package, reason
    packages: tuple[str, ...] = ()

    def missing(self) -> list[dict[str, Any]]:
        """``missing.recorded`` payloads for the packages not compared."""
        return [
            {
                "missing": {
                    "reason": "unsupported_project",
                    "targets": [],
                    "detail": f"API of {package} ({side}) not read: {reason}"[:1000],
                    "resolution": None,
                }
            }
            for side, package, reason in self.problems
        ]


def api_diff(git: Git, base: str, head: str, workdir: Path) -> ApiDiff:
    """The breaking changes of the project's packages from ``base`` to ``head``."""
    base_files, head_files = regular_files(git, base), regular_files(git, head)
    base_names, head_names = module_names(base_files.keys(), head_files.keys())
    blobs = read_blobs(
        git, [base_files[p] for p in base_names] + [head_files[p] for p in head_names]
    )
    trees, packages = {}, {}
    for side, files, names in (("base", base_files, base_names), ("head", head_files, head_names)):
        root = workdir / side
        if root.exists():
            shutil.rmtree(root)
        trees[side] = root
        packages[side] = _write_tree(root, {p: blobs[files[p]] for p in names}, names)
    where = {name: path for path, name in base_names.items()}
    where.update({name: path for path, name in head_names.items()})
    found = ApiDiff(packages=tuple(sorted(packages["base"])))
    loaders = {
        side: griffe.GriffeLoader(
            search_paths=[trees[side]], allow_inspection=False, store_source=False
        )
        for side in trees
    }
    for package in sorted(packages["base"]):
        old = _load(loaders["base"], package, "base", found)
        if old is None:
            continue
        if package not in packages["head"]:
            found.breaks.append(_removed_package(package, where))
            continue
        new = _load(loaders["head"], package, "head", found)
        if new is None:
            continue
        try:
            found.breaks += [_from_griffe(b, where) for b in griffe.find_breaking_changes(old, new)]
            found.breaks += list(_annotations(old, new, where, set()))
        except Exception as exc:  # noqa: BLE001 - a construct griffe cannot compare
            found.problems.append(("base..head", package, f"{type(exc).__name__}: {exc}"[:300]))
    for root in trees.values():
        shutil.rmtree(root, ignore_errors=True)
    found.breaks.sort(key=lambda b: (b.symbol, b.breakage, b.old or "", b.new or ""))
    return found


def _write_tree(root: Path, sources: Mapping[str, bytes], names: Mapping[str, str]) -> set[str]:
    """Each module's file at its module name's path; the top-level packages written."""
    packages = set()
    for path, name in names.items():
        parts = name.split(".")
        is_package = path.endswith("/__init__.py") or path == "__init__.py"
        target = (
            root.joinpath(*parts, "__init__.py")
            if is_package
            else root.joinpath(*parts[:-1], f"{parts[-1]}.py")
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sources[path])
        if is_package and len(parts) == 1 and parts[0] not in TEST_PACKAGES:
            packages.add(parts[0])
    return packages


def _load(loader: griffe.GriffeLoader, package: str, side: str, found: ApiDiff) -> Any:
    try:
        return loader.load(package)
    except Exception as exc:  # noqa: BLE001 - griffe's errors vary (syntax, a missing file)
        found.problems.append((side, package, f"{type(exc).__name__}: {exc}"[:300]))
        return None


def _symbol(obj: Any) -> str:
    path: str = obj.path
    module: str = obj.module.path if not obj.is_module else path
    qualname = path[len(module) + 1 :] if path != module else MODULE_QUALNAME
    return f"{module}:{qualname}#0"


def _short(value: Any) -> str | None:
    """A value as text: a parameter by its signature, an object by its value or kind."""
    if value is None:
        return None
    if isinstance(value, griffe.Parameter):
        text = value.name
        if value.annotation is not None:
            text += f": {value.annotation}"
        if value.default is not None:
            text += f" = {value.default}"
    elif isinstance(value, griffe.Object | griffe.Alias):
        own = getattr(value, "value", None)
        text = str(own) if own is not None else value.kind.value
    else:
        text = str(value)
    return text if len(text) <= _VALUE else text[: _VALUE - 1] + "…"


def _explain(path: str, kind: str, old: str | None, new: str | None) -> str:
    detail = f"{old} → {new}" if old is not None and new is not None else old or new
    text = f"{path}: {kind}" + (f" ({detail})" if detail else "")
    return text if len(text) <= EXPLANATION else text[: EXPLANATION - 1] + "…"


def _from_griffe(breakage: Any, where: Mapping[str, str]) -> ApiBreak:
    obj = breakage.obj
    old, new = _short(breakage.old_value), _short(breakage.new_value)
    return ApiBreak(
        symbol=_symbol(obj),
        file=where.get(obj.module.path),
        breakage=breakage.kind.name.lower(),
        explanation=_explain(obj.path, breakage.kind.value, old, new),
        old=old,
        new=new,
        source="griffe",
    )


def _removed_package(package: str, where: Mapping[str, str]) -> ApiBreak:
    return ApiBreak(
        symbol=f"{package}:{MODULE_QUALNAME}#0",
        file=where.get(package),
        breakage="object_removed",
        explanation=_explain(package, "Public package was removed", None, None),
        old="module",
        new=None,
        source="griffe",
    )


def _annotations(
    old: Any, new: Any, where: Mapping[str, str], seen: set[str]
) -> Iterator[ApiBreak]:
    """Return and attribute annotations present on both sides that read differently."""
    news = new.members
    for name, before in old.members.items():
        after = news.get(name)
        if before.is_alias or after is None or after.is_alias or not before.is_public:
            continue
        if before.kind != after.kind or before.path in seen:
            continue
        seen.add(before.path)
        if before.is_module or before.is_class:
            yield from _annotations(before, after, where, seen)
            continue
        if before.is_function:
            kind, was, now = "return_changed_type", before.returns, after.returns
            label = "Return annotation changed"
        elif before.is_attribute:
            kind, was, now = "attribute_changed_type", before.annotation, after.annotation
            label = "Attribute annotation changed"
        else:
            continue
        if was is None or now is None or " ".join(str(was).split()) == " ".join(str(now).split()):
            continue
        old_text, new_text = _short(str(was)), _short(str(now))
        yield ApiBreak(
            symbol=_symbol(after),
            file=where.get(after.module.path),
            breakage=kind,
            explanation=_explain(after.path, label, old_text, new_text),
            old=old_text,
            new=new_text,
            source="annotations",
        )
