"""S2's candidate tasks, chosen by the protocol's rules (J05; protocol §2, §3).

S2 takes fresh tasks: SWE-rebench's leaderboard splits, each a month of issues resolved after
the reviewer model's knowledge cutoff (1 June 2024 for gpt-oss-120b [OpenAI, model page,
checked 2026-10-18]). A task is a candidate when
- its environment pins Python 3.12 or newer (``install_config.python``): Repro's tracer needs
  ``sys.monitoring`` (J04's decision);
- it is graded with pytest (``install_config.log_parser`` is ``parse_log_pytest``);
- it has an environment image (``docker_image``) and a non-empty gold patch and test patch.

The rows come from the Hugging Face datasets server, page by page. That service serves the
dataset's current revision; the revision is read from the Hub's API at the same time and
written with the list, and each row's SHA-256 is kept, so a later fetch can be checked against
it. The list holds identifiers and metadata only: the dataset is CC-BY-4.0
[nebius/SWE-rebench-leaderboard], and its rows are fetched by ID, never re-hosted.

    uv run python -m repro_bench.tasks --splits 2025_09 ... 2026_03 --out <jsonl>
"""

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

DATASET: Final = "nebius/SWE-rebench-leaderboard"
ROWS: Final = "https://datasets-server.huggingface.co/rows"
HUB: Final = "https://huggingface.co/api/datasets/"
PAGE: Final = 100
MIN_PYTHON: Final = (3, 12)


def _get(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "repro-bench"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=120) as answer:  # noqa: S310 - fixed hosts
        return json.loads(answer.read())


def revision(dataset: str = DATASET) -> str:
    """The dataset's current revision on the Hub (the commit the datasets server serves)."""
    return str(_get(HUB + dataset)["sha"])


def rows(split: str, dataset: str = DATASET) -> Iterator[dict[str, Any]]:
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {
                "dataset": dataset,
                "config": "default",
                "split": split,
                "offset": offset,
                "length": PAGE,
            }
        )
        page = _get(f"{ROWS}?{query}")
        found = [row["row"] for row in page.get("rows", [])]
        yield from found
        offset += len(found)
        if not found or offset >= int(page.get("num_rows_total", 0)):
            return


def _config(record: Mapping[str, Any]) -> dict[str, Any]:
    config = record.get("install_config")
    config = json.loads(config) if isinstance(config, str) else config
    return config if isinstance(config, dict) else {}


def python_of(record: Mapping[str, Any]) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in str(_config(record).get("python")).split(".")[:2])
    except ValueError:
        return None


def why_not(record: Mapping[str, Any]) -> str | None:
    """Why a task is not a candidate, or None when it is."""
    config = _config(record)
    version = python_of(record)
    if version is None or version < MIN_PYTHON:
        return f"Python {config.get('python')}"
    if config.get("log_parser") != "parse_log_pytest":
        return f"log parser {config.get('log_parser')}"
    if not record.get("docker_image"):
        return "no environment image"
    if (
        not str(record.get("patch") or "").strip()
        or not str(record.get("test_patch") or "").strip()
    ):
        return "no gold patch or test patch"
    return None


def digest(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()


def candidate(record: Mapping[str, Any], split: str) -> dict[str, Any]:
    return {
        "instance_id": record["instance_id"],
        "split": split,
        "repo": record["repo"],
        "created_at": record.get("created_at"),
        "python": _config(record).get("python"),
        "image": record["docker_image"],
        "record_sha256": digest(record),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--splits", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True, help="the candidates (JSONL)")
    parser.add_argument("--records", type=Path, help="also keep the full rows here (not for git)")
    args = parser.parse_args(argv)
    pinned = revision()
    kept: list[dict[str, Any]] = []
    left_out: dict[str, int] = {}
    full = []
    for split in args.splits:
        for record in rows(split):
            reason = why_not(record)
            if reason is None:
                kept.append(candidate(record, split) | {"dataset_revision": pinned})
                full.append(record)
            else:
                left_out[reason] = left_out.get(reason, 0) + 1
    kept.sort(key=lambda row: (row["split"], row["instance_id"]))
    args.out.write_bytes("".join(json.dumps(r, sort_keys=True) + "\n" for r in kept).encode())
    if args.records:
        args.records.write_bytes(
            "".join(json.dumps(r, sort_keys=True) + "\n" for r in full).encode("utf-8")
        )
    sys.stdout.write(f"{len(kept)} candidates from {DATASET} at {pinned}\n")
    for reason, count in sorted(left_out.items(), key=lambda item: -item[1]):
        sys.stdout.write(f"  left out, {reason}: {count}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
