"""Sets a sandboxed command's resource limits, then becomes the command (POSIX; ADR-0004, L2).

Run as ``python -I -S _rlimits.py <limits as JSON> -- <command...>`` in the command's new
session: the limits apply to this process, ``os.execvp`` replaces it with the command, and
everything the command starts inherits them. Limits are set here, not in ``preexec_fn``, because
the engine has threads and Python's documentation warns that ``preexec_fn`` is not safe with
threads.

The standard library only, and nothing from the target is imported (``-I -S``).
"""

# ruff: noqa: PTH208 - a start-up launcher: os on purpose

import json
import os
import sys

if sys.platform != "win32":
    import resource

    def _user_threads() -> int:
        """The threads the real user has now: ``RLIMIT_NPROC`` counts all of them (Linux)."""
        uid = os.getuid()
        count = 0
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/status", encoding="ascii", errors="replace") as status:  # noqa: PTH123
                    fields = dict(line.split(":", 1) for line in status if ":" in line)
                if int(fields["Uid"].split()[0]) == uid:
                    count += int(fields["Threads"])
            except (OSError, KeyError, ValueError, IndexError):
                continue  # gone, or not readable
        return count

    def main() -> None:
        limits = json.loads(sys.argv[1])
        command = sys.argv[3:]
        memory = int(limits["memory_bytes"])
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if sys.platform.startswith("linux"):
            allowed = _user_threads() + int(limits["processes"])
            _, hard = resource.getrlimit(resource.RLIMIT_NPROC)
            cap = allowed if hard == resource.RLIM_INFINITY else min(allowed, hard)
            resource.setrlimit(resource.RLIMIT_NPROC, (cap, cap))
        try:
            os.execvp(command[0], command)  # noqa: S606 - the sandboxed command itself
        except OSError as exc:
            sys.stderr.write(f"repro sandbox: cannot run {command[0]!r}: {exc.strerror or exc}\n")
            sys.exit(127)

    if __name__ == "__main__":
        main()
