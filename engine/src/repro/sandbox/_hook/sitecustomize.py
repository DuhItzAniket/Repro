"""Repro's detection hook (ADR-0004, L1), loaded by every Python process a sandbox starts.

``site`` imports ``sitecustomize`` at start-up from ``sys.path``, and the sandbox puts this
directory first on ``PYTHONPATH``. The hook records network, subprocess and file-write attempts,
one JSON object per line, in the file named by ``REPRO_AUDIT_LOG``: file writes only outside the
directories in ``REPRO_AUDIT_ROOTS``, judged by where the path resolves, as the roots are (H03):
a link inside a root that leads out is outside, and a path that reaches a root through a link,
a junction, a short (8.3) name or a redirected folder is inside. It detects and never prevents;
code that bypasses Python's audited functions (C extensions, ``ctypes``) is not seen, and
Python's documentation says audit hooks are not a sandbox. Nothing here may raise into the
target. A ``sitecustomize`` of the environment's own is imported afterwards, as it would have
been.

The standard library only, and ``os.path`` rather than ``pathlib``: this runs at the start of
every Python process of the target, in the target's interpreter.
"""
# ruff: noqa: PTH100, PTH120 - os.path on purpose (see above)

import json
import os
import sys

_NETWORK = frozenset(
    {
        "socket.connect",
        "socket.sendto",
        "socket.sendmsg",
        "socket.getaddrinfo",
        "socket.gethostbyname",
    }
)
_PROCESS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.startfile",
        "os.startfile/2",
        "os.fork",
        "os.forkpty",
    }
)
_FILES = frozenset({"open", "os.remove", "os.rename", "os.rmdir", "shutil.rmtree"})
_WATCHED = _NETWORK | _PROCESS | _FILES
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
#: Records per process; then one "truncated" record.
_LIMIT = 1000
_DETAIL = 300


def _text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return " ".join(_text(item) for item in value)
    if isinstance(value, (str, bytes)):
        return os.fsdecode(value)
    return repr(value)


def _address(address: object) -> str:
    """``host:port`` for an IP address tuple; a Unix socket's path as it is."""
    if isinstance(address, tuple) and len(address) > 1:
        return f"{_text(address[0])}:{address[1]}"
    return _text(address)


def _network(event: str, args: tuple[object, ...]) -> str:
    if event == "socket.getaddrinfo":
        return f"{_text(args[0])}:{args[1]}"
    if event == "socket.gethostbyname":
        return _text(args[0])
    return _address(args[1])  # socket.connect, sendto, sendmsg: (self, address)


def _process(event: str, args: tuple[object, ...]) -> str:
    if event == "subprocess.Popen":  # (executable, args, cwd, env)
        return _text(args[1] if args[1] is not None else args[0])
    if event == "os.spawn":  # (mode, path, args, env)
        return _text(args[2])
    if event in {"os.exec", "os.posix_spawn"}:  # (path, args, env)
        return _text(args[1])
    if event in {"os.fork", "os.forkpty"}:
        return ""
    return _text(args[0])  # os.system, os.startfile


def _normal(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def _real(path: str) -> str:
    """Where ``path`` is, links and the like resolved; as written if that fails."""
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return _normal(path)


class _Recorder:
    def __init__(self, fd: int, roots: tuple[str, ...], quiet: frozenset[str]) -> None:
        self.fd = fd
        self.roots = roots
        self.quiet = quiet
        self.written = 0
        self.busy = False

    def outside(self, path: object) -> bool:
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not isinstance(path, str):
            return False  # a file descriptor: its path is unknown here
        if _normal(path) in self.quiet:
            return False
        full = _real(path)
        if full in self.quiet:
            return False
        return not any(full == root or full.startswith(root + os.sep) for root in self.roots)

    def file_write(self, event: str, args: tuple[object, ...]) -> str | None:
        if event == "open":  # (path, mode, flags): mode is None for os.open
            path, mode, flags = args[0], args[1], args[2]
            if isinstance(mode, str):
                writes = any(c in mode for c in "wax+")
            else:
                writes = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
            return _text(path) if writes and self.outside(path) else None
        if event == "os.rename":  # (src, dst, ...)
            moved = self.outside(args[0]) or self.outside(args[1])
            return f"{_text(args[0])} -> {_text(args[1])}" if moved else None
        return _text(args[0]) if self.outside(args[0]) else None

    def record(self, kind: str, event: str, detail: str) -> None:
        if self.written > _LIMIT:
            return
        self.written += 1
        if self.written > _LIMIT:
            kind, event, detail = "truncated", "", f"more than {_LIMIT} attempts"
        line = json.dumps(
            {
                "kind": kind,
                "event": event,
                "detail": detail[:_DETAIL],
                "pid": os.getpid(),
                "test": os.environ.get("PYTEST_CURRENT_TEST"),
            }
        )
        os.write(self.fd, line.encode("ascii", "backslashreplace") + b"\n")

    def __call__(self, event: str, args: tuple[object, ...]) -> None:
        if event not in _WATCHED or self.busy:
            return
        self.busy = True
        try:
            if event in _NETWORK:
                self.record("network", event, _network(event, args))
            elif event in _PROCESS:
                self.record("subprocess", event, _process(event, args))
            else:
                detail = self.file_write(event, args)
                if detail is not None:
                    self.record("file", event, detail)
        except Exception:  # noqa: BLE001, S110 - the target must never see the hook fail
            pass
        finally:
            self.busy = False


def _install() -> None:
    log = os.environ.get("REPRO_AUDIT_LOG")
    if not log:
        return
    roots = tuple(
        {_real(root) for root in os.environ.get("REPRO_AUDIT_ROOTS", "").split(os.pathsep) if root}
    )
    try:
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    except OSError:
        return
    quiet = frozenset(form(path) for path in (log, os.devnull) for form in (_normal, _real))
    sys.addaudithook(_Recorder(fd, roots, quiet))


def _chain() -> None:
    """Imports the environment's own ``sitecustomize``, if it has one."""
    import importlib.util  # noqa: PLC0415 - only needed here
    from importlib.machinery import PathFinder  # noqa: PLC0415

    here = _normal(os.path.dirname(__file__))
    path = [p for p in sys.path if _normal(p or os.curdir) != here]
    spec = PathFinder.find_spec("sitecustomize", path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


_install()
_chain()
