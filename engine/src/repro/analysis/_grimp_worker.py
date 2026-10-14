"""grimp over a tree of a target's packages, in a process of its own (see ``imports.py``).

Run as ``python -I -S _grimp_worker.py``: no site-packages, ``.pth`` hooks or script directory on
``sys.path``. The tree is never put on ``sys.path`` either: each package's directory is handed
to grimp through its package-finder setting, so no ``find_spec`` resolves a target name, and
nothing of the target is imported. grimp parses the sources without running them.

Request (stdin, JSON): ``{"grimp_path": str, "tree": str, "packages": {name: directory}}``.
Response (stdout, JSON): ``{"imports": [[importer, imported], ...], "unparsable": [[path,
reason], ...]}``, with paths relative to the tree. A file grimp cannot parse is emptied and the
graph rebuilt without its imports, up to ``MAX_RETRIES`` times.
"""

import json
import os
import sys

MAX_RETRIES = 100


def main() -> None:
    request = json.load(sys.stdin)
    sys.path.append(request["grimp_path"])
    import grimp  # noqa: PLC0415 - only once the path to grimp itself is known
    from grimp.application.config import settings  # noqa: PLC0415
    from grimp.application.ports.packagefinder import AbstractPackageFinder  # noqa: PLC0415
    from grimp.exceptions import SourceSyntaxError  # noqa: PLC0415

    directories: dict[str, str] = request["packages"]

    class TreeFinder(AbstractPackageFinder):
        def determine_package_directories(
            self,
            package_name: str,
            file_system: object,  # noqa: ARG002 - grimp passes it by keyword
        ) -> set[str]:
            return {directories[package_name]}

    settings.configure(PACKAGE_FINDER=TreeFinder())
    tree = request["tree"]
    unparsable: list[list[str]] = []
    imports: list[list[str]] = []
    if directories:
        for _ in range(MAX_RETRIES + 1):
            try:
                graph = grimp.build_graph(*sorted(directories), cache_dir=None)
            except SourceSyntaxError as exc:
                path = os.path.relpath(exc.filename, tree).replace(os.sep, "/")
                where = f"line {exc.lineno}" if exc.lineno else "unknown line"
                unparsable.append([path, f"grimp cannot parse it ({where})"])
                with open(exc.filename, "wb"):  # noqa: PTH123 - emptied: its imports are lost
                    pass
                continue
            imports = sorted(
                [importer, imported]
                for importer in graph.modules
                for imported in graph.find_modules_directly_imported_by(importer)
            )
            break
        else:
            unparsable.append(["", f"more than {MAX_RETRIES} files grimp cannot parse"])
    json.dump({"imports": imports, "unparsable": unparsable}, sys.stdout)


if __name__ == "__main__":
    main()
