"""A repository's ``repro.yml`` (F01; ARCHITECTURE §12, PRODUCT.md): parsed, validated against
its JSON Schema (``repro-yml.schema.json``, beside this file), with defaults.

The file comes from the target repository, so it is untrusted input:

- at most ``MAX_BYTES``, UTF-8, one YAML document;
- read with PyYAML's safe loader only (no Python objects constructed from tags);
- anchors and aliases refused (an alias can make a small file expand without bound) and
  duplicate keys refused (YAML keeps the last silently);
- every error names the file, its line and column, and the path into the document, so it can
  be fixed from the message alone;
- a ``forbidden_paths`` pattern that could never match a repository path (a backslash, a
  leading ``/``, a ``..`` segment) is an error, not a rule that silently passes (F02).

Policy is read from the **base** ref; what head did to the file is compared, and a change that
weakens it (an invariant dropped or relaxed, a threshold raised) is listed (``weakenings``).
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Final

import jsonschema
import yaml

FILE: Final = "repro.yml"
MAX_BYTES: Final = 64 * 1024
SCHEMA_PATH: Final = Path(__file__).with_name("repro-yml.schema.json")
#: The invariants Repro knows (the schema's), in the order they are listed.
INVARIANTS: Final = (
    "public_api_stable",
    "no_new_dependencies",
    "no_network",
    "perf_budget",
    "forbidden_paths",
)


@dataclass(frozen=True, slots=True)
class PolicyIssue:
    """Why a policy file was not accepted, and where."""

    file: str
    line: int | None  # 1-based
    column: int | None  # 1-based
    path: str  # into the document: "invariants[0].perf_budget"; "" for the whole file
    message: str

    def __str__(self) -> str:
        where = self.file
        if self.line is not None:
            where += f":{self.line}" + (f":{self.column}" if self.column is not None else "")
        return f"{where}: {self.path + ': ' if self.path else ''}{self.message}"


class PolicyError(ValueError):
    """A policy file that is not valid; ``issues`` says what is wrong, where."""

    def __init__(self, issues: Sequence[PolicyIssue]) -> None:
        super().__init__("; ".join(str(i) for i in issues))
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class Invariant:
    name: str
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Policy:
    """The policy in force: enabled invariants and thresholds."""

    invariants: tuple[Invariant, ...] = ()
    require_explicit_claims: bool = False
    max_uncovered_changed_symbols: float = 0.25

    def invariant(self, name: str) -> Invariant | None:
        return next((i for i in self.invariants if i.name == name), None)

    def document(self) -> dict[str, Any]:
        """The policy as data (evidence, the card)."""
        return {
            "invariants": [{i.name: _written(i)} for i in self.invariants],
            "claims": {"require_explicit": self.require_explicit_claims},
            "missing": {"max_uncovered_changed_symbols": self.max_uncovered_changed_symbols},
        }


DEFAULT: Final = Policy()


def _written(invariant: Invariant) -> Any:
    """An invariant's value as ``repro.yml`` writes it."""
    if invariant.name == "forbidden_paths":
        return list(invariant.options.get("paths", ()))
    return dict(invariant.options) or True


@cache
def schema() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return loaded


def load(data: bytes, file: str = FILE) -> Policy:
    """The policy ``data`` holds; ``PolicyError`` with every issue found if it is not valid."""
    if len(data) > MAX_BYTES:
        raise PolicyError([PolicyIssue(file, None, None, "", f"larger than {MAX_BYTES} bytes")])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PolicyError(
            [PolicyIssue(file, None, None, "", f"not UTF-8 ({exc.reason})")]
        ) from None
    node, document = _parse(text, file)
    if node is None:  # an empty file: the defaults
        return DEFAULT
    issues = list(_schema_issues(document, node, file))
    issues += list(_duplicate_invariants(document, node, file))
    issues += list(_path_issues(document, node, file))
    if issues:
        raise PolicyError(issues)
    return _policy(document)


def _parse(text: str, file: str) -> tuple[yaml.Node | None, Any]:
    loader = yaml.SafeLoader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            return None, None
        _check_nodes(node, file)
        document = loader.construct_document(node)
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line, column = (mark.line + 1, mark.column + 1) if mark is not None else (None, None)
        message = " ".join(str(p) for p in (exc.context, exc.problem) if p) or "not valid YAML"
        raise PolicyError([PolicyIssue(file, line, column, "", message)]) from None
    except yaml.YAMLError as exc:
        raise PolicyError([PolicyIssue(file, None, None, "", f"not valid YAML: {exc}")]) from None
    except RecursionError:
        raise PolicyError([PolicyIssue(file, None, None, "", "nested too deeply")]) from None
    finally:
        loader.dispose()
    return node, document


def _check_nodes(root: yaml.Node, file: str) -> None:
    """No node twice (an alias), no duplicate key; ``PolicyError`` at the first found."""
    seen: set[int] = set()
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            raise PolicyError([_at(node, file, "", "anchors and aliases are not allowed")])
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            keys: set[Any] = set()
            for key, value in node.value:
                text = key.value if isinstance(key, yaml.ScalarNode) else None
                if text is not None and text in keys:
                    raise PolicyError([_at(key, file, "", f"duplicate key {text!r}")])
                keys.add(text)
                stack += [key, value]
        elif isinstance(node, yaml.SequenceNode):
            stack += node.value


def _at(node: yaml.Node | None, file: str, path: str, message: str) -> PolicyIssue:
    mark = node.start_mark if node is not None else None
    if mark is None:
        return PolicyIssue(file, None, None, path, message)
    return PolicyIssue(file, mark.line + 1, mark.column + 1, path, message)


def _node_at(root: yaml.Node, path: Sequence[Any]) -> yaml.Node:
    """The deepest node along ``path`` (keys and indices into the document)."""
    node = root
    for step in path:
        if isinstance(node, yaml.MappingNode):
            found = next((v for k, v in node.value if getattr(k, "value", None) == step), None)
        elif (
            isinstance(node, yaml.SequenceNode) and isinstance(step, int) and step < len(node.value)
        ):
            found = node.value[step]
        else:
            found = None
        if found is None:
            break
        node = found
    return node


def _path_text(path: Sequence[Any]) -> str:
    text = ""
    for step in path:
        text += f"[{step}]" if isinstance(step, int) else (f".{step}" if text else str(step))
    return text


def _schema_issues(document: Any, root: yaml.Node, file: str) -> Iterator[PolicyIssue]:
    validator = jsonschema.Draft202012Validator(schema())
    errors = sorted(
        validator.iter_errors(document), key=lambda e: [str(p) for p in e.absolute_path]
    )
    for error in errors:
        path = list(error.absolute_path)
        yield _at(_node_at(root, path), file, _path_text(path), _message(error))


def _message(error: jsonschema.ValidationError) -> str:
    """A shorter message for the schema's choices, which jsonschema words for itself."""
    if error.validator in ("oneOf", "anyOf") and error.context:
        best = min(error.context, key=lambda e: len(list(e.absolute_path)))
        return best.message
    rules = error.schema
    if (
        error.validator == "additionalProperties"
        and isinstance(error.instance, dict)
        and isinstance(rules, Mapping)
    ):
        known = sorted(rules.get("properties", {}))
        extra = sorted(set(error.instance) - set(known))
        return f"unknown key {', '.join(map(repr, extra))} (known: {', '.join(known)})"
    return error.message


def _duplicate_invariants(document: Any, root: yaml.Node, file: str) -> Iterator[PolicyIssue]:
    seen: set[str] = set()
    for index, item in enumerate(
        document.get("invariants", []) if isinstance(document, dict) else []
    ):
        if not isinstance(item, dict) or len(item) != 1:
            continue
        (name,) = item
        if name in seen:
            yield _at(
                _node_at(root, ["invariants", index]),
                file,
                f"invariants[{index}]",
                f"{name} is listed twice",
            )
        seen.add(name)


def path_problem(pattern: str) -> str | None:
    """Why a ``forbidden_paths`` pattern could never match a repository path (git's paths are
    relative, with ``/``), or None."""
    if "\\" in pattern:
        return "use / between path segments, not \\"
    if pattern.startswith("/"):
        return "paths are relative to the repository root: no leading /"
    segments = pattern.removeprefix("./").removesuffix("/").split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        return "no empty, '.' or '..' path segments"
    return None


def _path_issues(document: Any, root: yaml.Node, file: str) -> Iterator[PolicyIssue]:
    """A pattern that matches nothing would pass every change: refused, not ignored."""
    items = document.get("invariants", []) if isinstance(document, dict) else []
    for index, item in enumerate(items if isinstance(items, list) else []):
        patterns = item.get("forbidden_paths") if isinstance(item, dict) else None
        for position, pattern in enumerate(patterns if isinstance(patterns, list) else []):
            problem = path_problem(pattern) if isinstance(pattern, str) else None
            if problem is not None:
                path = ["invariants", index, "forbidden_paths", position]
                yield _at(_node_at(root, path), file, _path_text(path), f"{pattern!r}: {problem}")


def _policy(document: Mapping[str, Any]) -> Policy:
    invariants = []
    for item in document.get("invariants", []):
        ((name, value),) = item.items()
        if value is False:
            continue  # declared and switched off
        if isinstance(value, list):  # forbidden_paths
            options: dict[str, Any] = {"paths": list(value)}
        else:
            options = dict(value) if isinstance(value, dict) else {}
        invariants.append(Invariant(name, options))
    order = {name: i for i, name in enumerate(INVARIANTS)}
    claims = document.get("claims", {})
    missing = document.get("missing", {})
    return Policy(
        tuple(sorted(invariants, key=lambda i: order[i.name])),
        bool(claims.get("require_explicit", False)),
        float(missing.get("max_uncovered_changed_symbols", 0.25)),
    )


# -- base and head -------------------------------------------------------------------------------


def weakenings(base: Policy, head: Policy) -> list[str]:
    """How head's policy is weaker than base's (an empty list: it is not)."""
    found = []
    for before in base.invariants:
        after = head.invariant(before.name)
        if after is None:
            found.append(f"{before.name} removed")
            continue
        found += _relaxed(before, after)
    if base.require_explicit_claims and not head.require_explicit_claims:
        found.append("claims.require_explicit turned off")
    if head.max_uncovered_changed_symbols > base.max_uncovered_changed_symbols:
        found.append(
            "missing.max_uncovered_changed_symbols raised from "
            f"{base.max_uncovered_changed_symbols} to {head.max_uncovered_changed_symbols}"
        )
    return found


def _relaxed(before: Invariant, after: Invariant) -> list[str]:
    name = before.name
    if name in ("public_api_stable", "no_new_dependencies"):
        key = "except" if name == "public_api_stable" else "allow"
        added = sorted(set(after.options.get(key, ())) - set(before.options.get(key, ())))
        return [f"{name}: {key} gains {', '.join(added)}"] if added else []
    if name == "perf_budget":
        old, new = before.options["max_regression"], after.options["max_regression"]
        return [f"perf_budget: max_regression raised from {old} to {new}"] if new > old else []
    if name == "forbidden_paths":
        gone = sorted(set(before.options.get("paths", ())) - set(after.options.get("paths", ())))
        return [f"forbidden_paths: no longer forbids {', '.join(gone)}"] if gone else []
    return []
