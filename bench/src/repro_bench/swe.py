"""SWE-format instances as Repro's input, under the evaluation's input contract (J01).

A SWE-bench instance already has a change's shape: the repository at ``base_commit``, a problem
statement, and ground truth (``patch``, ``test_patch``, ``FAIL_TO_PASS``, ``PASS_TO_PASS``,
``hints_text``) [SWE-bench dataset card, princeton-nlp/SWE-bench, checked 2026-10-18]. An agent's
prediction is one JSON object a line with ``instance_id``, ``model_name_or_path`` and
``model_patch`` [SWE-bench, ``docs/guides/evaluation.md``, checked 2026-10-18]: it is the head.
SWE-rebench adds the task's environment image (``docker_image``) [nebius/SWE-rebench dataset
card, checked 2026-10-18].

**The input contract** (``docs/paper/EVALUATION_PROTOCOL.md`` §2, ADR-0010). Every system gets
exactly the repository at base, the agent's diff and the claim text: the problem statement and
the agent's final summary, or a fixed sentence when there is none. Everything else is withheld:
the ground truth above, and the instance's ID too, which carries a number on GitHub
(``repo_owner__repo_name-issue_number`` [SWE-bench, ``docs/guides/evaluation.md``]) that leads
to the fix. ``seal`` builds a system's input from an allow-list, so a field a dataset adds later is
withheld as well; the SHA-256 of the sealed input is logged with every run.

The work is split so the runner never reads a dataset: ``seal`` reads instances and predictions
and writes the sealed inputs and the manifest; ``run`` reads sealed inputs alone.

**The head commit** is made without a working tree: the diff is applied to a temporary index of
the base commit and written as a tree, so nothing of the target is checked out on the host
(ground rule 5).

**The manifest** pins what an evaluation ran on: each instance's source (dataset, split and
revision), base commit, environment image by digest, and the SHA-256 of the patch under test.

    uv run python -m repro_bench.swe seal --instances <jsonl> --predictions <jsonl>
        --dataset <name> --split <split> --revision <rev> --out <dir> [--pin-images]
    uv run python -m repro_bench.swe run --sealed <dir>/sealed.jsonl --mirrors <dir>
        --out <dir> [--sandbox process|docker] [--limit N] [-- <repro run options>]
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from repro import __version__
from repro.gitops import Git, GitError

#: Ground truth: what the dataset knows about the right answer, never a system's input.
WITHHELD: Final = ("patch", "test_patch", "FAIL_TO_PASS", "PASS_TO_PASS", "hints_text")
#: The claim when the agent left no summary (protocol §2).
FIXED_CLAIM: Final = "Fixes the issue above without regressions."
TITLE_MAX: Final = 200
RUN_TIMEOUT_S: Final = 3600.0
_SHA: Final = re.compile(r"^[0-9a-f]{40}$")
_REPO: Final = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_DIGEST: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
#: A run that ended with its card made: "completed", or "failed" when a job failed (J04).
_ENDED: Final = re.compile(r"\b(run_[0-9A-HJKMNP-TV-Z]{26}) (?:completed|failed)\b")
_LABELS: Final = (None, "CORRECT", "INCORRECT", "UNCERTAIN")


class ContractError(Exception):
    """An instance, a prediction or a manifest that breaks the input contract."""


@dataclass(frozen=True)
class Instance:
    """A task: what a system may see, and, apart, the ground truth it may not."""

    instance_id: str
    repo: str  # owner/name on GitHub
    base_commit: str
    problem_statement: str
    image: str | None = None  # the environment image, as the dataset names it
    truth: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Instance":
        for key in ("instance_id", "repo", "base_commit", "problem_statement"):
            if not isinstance(record.get(key), str) or not record[key]:
                raise ContractError(f"an instance needs {key}")
        if not _REPO.match(record["repo"]):
            raise ContractError(f"{record['instance_id']}: repo {record['repo'][:60]!r}")
        if not _SHA.match(record["base_commit"]):
            raise ContractError(f"{record['instance_id']}: base_commit is not a commit")
        image = record.get("docker_image") or record.get("image_name")
        return cls(
            instance_id=record["instance_id"],
            repo=record["repo"],
            base_commit=record["base_commit"],
            problem_statement=record["problem_statement"],
            image=image if isinstance(image, str) and image else None,
            truth={key: record[key] for key in WITHHELD if key in record},
        )


@dataclass(frozen=True)
class Prediction:
    """An agent's patch for an instance, in SWE-bench's predictions format."""

    instance_id: str
    model: str
    patch: str
    #: The agent's final summary, when its trajectory has one.
    summary: str | None = None

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Prediction":
        for key in ("instance_id", "model_name_or_path", "model_patch"):
            if not isinstance(record.get(key), str):
                raise ContractError(f"a prediction needs {key}")
        summary = record.get("summary")
        return cls(
            record["instance_id"],
            record["model_name_or_path"],
            record["model_patch"],
            summary if isinstance(summary, str) and summary.strip() else None,
        )

    @property
    def patch_sha256(self) -> str:
        return hashlib.sha256(self.patch.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Sealed:
    """Exactly what a system receives (protocol §2), and nothing else."""

    repo: str
    base_commit: str
    diff: str
    claim: str

    def canonical(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode("utf-8")

    @property
    def digest(self) -> str:
        """The SHA-256 of what the system saw, logged with its run."""
        return hashlib.sha256(self.canonical()).hexdigest()

    @property
    def title(self) -> str:
        """The pull request's title Repro gets: the claim's first line (the issue's title)."""
        first = next((line.strip() for line in self.claim.splitlines() if line.strip()), "")
        return first[:TITLE_MAX] or "The patch under evaluation"


def claim_text(instance: Instance, prediction: Prediction) -> str:
    """The problem statement, then the agent's summary, or the fixed sentence when it left none."""
    return f"{instance.problem_statement.strip()}\n\n{prediction.summary or FIXED_CLAIM}"


def seal(instance: Instance, prediction: Prediction) -> Sealed:
    """A system's input, built from the allowed fields alone (raises ``ContractError``)."""
    if prediction.instance_id != instance.instance_id:
        raise ContractError(
            f"{prediction.instance_id} is not a prediction for {instance.instance_id}"
        )
    if not prediction.patch.strip():
        raise ContractError(f"{instance.instance_id}: the prediction's patch is empty")
    return Sealed(
        instance.repo, instance.base_commit, prediction.patch, claim_text(instance, prediction)
    )


@dataclass(frozen=True)
class Task:
    """A sealed input with the keys that identify it in results: never shown to a system."""

    instance_id: str
    model: str
    patch_sha256: str
    input: Sealed

    def row(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "model": self.model,
            "patch_sha256": self.patch_sha256,
            "input_sha256": self.input.digest,
            "input": asdict(self.input),
        }

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Task":
        given = row.get("input")
        if not isinstance(given, dict) or set(given) != set(Sealed.__dataclass_fields__):
            raise ContractError(
                f"{row.get('instance_id')}: a sealed input has exactly "
                f"{sorted(Sealed.__dataclass_fields__)}"
            )
        sealed = Sealed(**given)
        if row.get("input_sha256") != sealed.digest:
            raise ContractError(f"{row.get('instance_id')}: the sealed input was changed")
        return cls(str(row["instance_id"]), str(row["model"]), str(row["patch_sha256"]), sealed)


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as lines:
        for number, line in enumerate(lines, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as exc:
                    raise ContractError(f"{path.name}:{number}: not JSON ({exc})") from None


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.write_bytes(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode("utf-8")
    )


# -- the change Repro runs ------------------------------------------------------------------------


def fetch_base(mirror: Path, repo: str, base_commit: str, *, source: str | None = None) -> Git:
    """A bare mirror holding ``base_commit``, fetched by its hash from ``repo`` on GitHub (or
    from ``source``, a test's local repository)."""
    mirror.mkdir(parents=True, exist_ok=True)
    git = Git(mirror, timeout_s=1800)
    if not (mirror / "HEAD").is_file():
        git.run("init", "--bare", "--quiet")
    if not _has(git, base_commit):
        remote = source or f"https://github.com/{repo}.git"
        try:
            git.run("fetch", "--quiet", "--no-tags", "--end-of-options", remote, base_commit)
        except GitError as exc:
            raise ContractError(f"{repo}: fetching {base_commit[:12]} failed: {exc}") from None
        if not _has(git, base_commit):
            raise ContractError(f"{repo} served no commit {base_commit}")
    return git


def _has(git: Git, sha: str) -> bool:
    try:
        git.run("cat-file", "-e", "--end-of-options", f"{sha}^{{commit}}")
    except GitError:
        return False
    return True


def head_commit(git: Git, sealed: Sealed) -> str:
    """The base commit with the diff applied, as a commit, written without a working tree."""
    with tempfile.TemporaryDirectory(prefix="repro-swe-") as tmp:
        patch = Path(tmp) / "change.diff"
        patch.write_bytes(sealed.diff.encode("utf-8"))
        env = git.environment() | {
            "GIT_INDEX_FILE": str(Path(tmp) / "index"),
            "GIT_AUTHOR_NAME": "Repro benchmark",
            "GIT_AUTHOR_EMAIL": "bench@repro.invalid",
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_NAME": "Repro benchmark",
            "GIT_COMMITTER_EMAIL": "bench@repro.invalid",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
        }
        try:
            _git(git, env, "read-tree", "--end-of-options", sealed.base_commit)
            _git(git, env, "apply", "--cached", "--whitespace=nowarn", "--", str(patch))
            tree = _git(git, env, "write-tree")
            message = "The patch under evaluation"
            return _git(git, env, "commit-tree", tree, "-p", sealed.base_commit, "-m", message)
        except GitError as exc:
            raise ContractError(
                f"the patch does not apply to {sealed.base_commit[:12]}: {exc}"
            ) from None


def _git(git: Git, env: Mapping[str, str], *args: str) -> str:
    """``git <args>`` with ``env`` (``Git.run`` takes none): its stdout, stripped."""
    try:
        done = subprocess.run(  # noqa: S603 - git, hardened like every Repro git call
            git.command(*args),
            env=dict(env),
            capture_output=True,
            check=False,
            timeout=git.timeout_s,
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out") from None
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GitError(f"git {args[0]}: {said[-1] if said else done.returncode}")
    return done.stdout.decode("utf-8", "replace").strip()


def pr_file(sealed: Sealed) -> str:
    """``repro run --pr-file``'s text: the title line, then the claim as the description."""
    return f"{sealed.title}\n{sealed.claim}"


def repro_argv(sealed: Sealed, mirror: Path, head: str, pr: Path) -> list[str]:
    """``repro run``'s arguments for a sealed input; ``pr`` holds ``pr_file``'s text."""
    return [
        "run", "--repo", str(mirror), "--base", sealed.base_commit, "--head", head,
        "--pr-file", str(pr), "--no-serve",
    ]  # fmt: skip


@dataclass(frozen=True)
class Outcome:
    """One ``repro run`` of a task: what came out, and the digest of what went in."""

    instance_id: str
    model: str
    patch_sha256: str
    input_sha256: str
    head: str | None
    run_id: str | None
    status: str  # the card's, or why there is none
    seconds: float
    repro_version: str = __version__


def run_task(
    task: Task,
    mirrors: Path,
    cards: Path,
    *,
    env: Mapping[str, str],
    extra: Sequence[str] = (),
    source: str | None = None,
) -> Outcome:
    """Runs Repro on ``task`` and writes its card to ``cards/<run id>.json``."""
    sealed = task.input
    started = time.monotonic()

    def ended(status: str, head: str | None = None, run_id: str | None = None) -> Outcome:
        seconds = round(time.monotonic() - started, 1)
        return Outcome(
            task.instance_id,
            task.model,
            task.patch_sha256,
            sealed.digest,
            head,
            run_id,
            status,
            seconds,
        )

    owner, _, name = sealed.repo.partition("/")
    try:
        git = fetch_base(
            mirrors / owner / f"{name}.git", sealed.repo, sealed.base_commit, source=source
        )
        head = head_commit(git, sealed)
    except ContractError as exc:
        return ended(f"no run: {exc}")
    with tempfile.TemporaryDirectory(prefix="repro-swe-pr-") as tmp:
        pr = Path(tmp) / "pr.txt"
        pr.write_bytes(pr_file(sealed).encode("utf-8"))
        argv = [sys.executable, "-m", "repro", *repro_argv(sealed, git.repo, head, pr), *extra]
        done = subprocess.run(  # noqa: S603 - this interpreter, with Repro's own arguments
            argv, env=dict(env), capture_output=True, timeout=RUN_TIMEOUT_S, check=False
        )
    said = done.stderr.decode("utf-8", "replace")
    found = _ENDED.search(said)
    if found is None:
        last = said.strip().splitlines()[-1:] or [f"exit status {done.returncode}"]
        return ended(f"no card: {last[0][:300]}", head)
    run_id = found[1]
    card = subprocess.run(  # noqa: S603 - this interpreter, with Repro's own arguments
        [sys.executable, "-m", "repro", "export", run_id, "--format", "json"],
        env=dict(env),
        capture_output=True,
        check=False,
        timeout=300,
    )
    if card.returncode != 0:
        return ended("no card: repro export failed", head, run_id)
    cards.mkdir(parents=True, exist_ok=True)
    (cards / f"{run_id}.json").write_bytes(card.stdout.removesuffix(b"\n"))
    return ended(str(json.loads(card.stdout)["status"]), head, run_id)


# -- the manifest -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One (instance, patch) pair an evaluation ran on, pinned."""

    instance_id: str
    dataset: str  # e.g. nebius/SWE-rebench
    split: str
    revision: str  # the dataset's revision (a commit of its repository)
    repo: str
    base_commit: str
    image: str | None  # name@sha256:..., when the environment image is pinned
    patch_sha256: str
    model: str
    label: str | None = None  # CORRECT, INCORRECT or UNCERTAIN, once labelled (J02, J06)

    def check(self) -> None:
        if not _SHA.match(self.base_commit):
            raise ContractError(f"{self.instance_id}: base_commit is not a commit")
        if self.image is not None and not _DIGEST.match(self.image.rpartition("@")[2]):
            raise ContractError(f"{self.instance_id}: image {self.image!r} is not pinned by digest")
        if not re.fullmatch(r"[0-9a-f]{64}", self.patch_sha256):
            raise ContractError(f"{self.instance_id}: patch_sha256 is not a SHA-256")
        if self.label not in _LABELS:
            raise ContractError(f"{self.instance_id}: label {self.label!r}")


def entry(
    instance: Instance,
    prediction: Prediction,
    *,
    dataset: str,
    split: str,
    revision: str,
    image: str | None = None,
) -> Entry:
    made = Entry(
        instance.instance_id,
        dataset,
        split,
        revision,
        instance.repo,
        instance.base_commit,
        image,
        prediction.patch_sha256,
        prediction.model,
    )
    made.check()
    return made


def write_manifest(path: Path, entries: Iterable[Entry]) -> None:
    rows = sorted(entries, key=lambda e: (e.instance_id, e.model, e.patch_sha256))
    for row in rows:
        row.check()
    _write_jsonl(path, (asdict(row) for row in rows))


def read_manifest(path: Path) -> list[Entry]:
    found = []
    for record in read_jsonl(path):
        try:
            made = Entry(**record)
        except TypeError as exc:
            raise ContractError(f"{path.name}: {exc}") from None
        made.check()
        found.append(made)
    return found


# -- images, by digest ----------------------------------------------------------------------------


def repository(image: str) -> str:
    """An image reference's repository, as ``RepoDigests`` names it: no tag or digest, and no
    ``docker.io/`` or ``library/`` (Docker's defaults)."""
    name = image.partition("@")[0]
    slash = name.rfind("/")
    if ":" in name[slash + 1 :]:
        name = name[: name.rindex(":")]
    name = name.removeprefix("docker.io/")
    return name.removeprefix("library/")


def pinned(image: str, *, pull: bool = False, docker: str = "docker") -> str:
    """``image`` as ``repository@sha256:...``, by the registry digest Docker recorded when it
    pulled it: a tag can move, a digest names one image. With ``pull`` it is pulled first; a
    reference already pinned is checked against the image on this machine."""
    if pull:
        done = subprocess.run(  # noqa: S603 - docker, with a name from the dataset
            [docker, "pull", "--quiet", "--", image], capture_output=True, check=False, timeout=3600
        )
        if done.returncode != 0:
            raise ContractError(f"pulling {image} failed")
    done = subprocess.run(  # noqa: S603 - docker, with a name from the dataset
        [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", "--", image],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        raise ContractError(f"{image} is not on this machine: pull it first")
    wanted = repository(image)
    digests = [str(d) for d in json.loads(done.stdout or b"[]") or []]
    mine = [d for d in digests if repository(d) == wanted]
    if not mine:
        raise ContractError(f"{image} has no registry digest here (built locally?)")
    given = image.rpartition("@")[2]
    if _DIGEST.match(given):
        if f"{wanted}@{given}" not in mine:
            raise ContractError(f"{image}: the image on this machine has another digest")
        return f"{wanted}@{given}"
    return mine[0]


# -- the command ----------------------------------------------------------------------------------


def _seal_command(args: argparse.Namespace) -> int:
    instances = {}
    for record in read_jsonl(args.instances):
        made = Instance.from_record(record)
        instances[made.instance_id] = made
    tasks, entries = [], []
    for record in read_jsonl(args.predictions):
        prediction = Prediction.from_record(record)
        instance = instances.get(prediction.instance_id)
        if instance is None:
            raise ContractError(f"{prediction.instance_id} is not in {args.instances.name}")
        sealed = seal(instance, prediction)
        image = (
            pinned(instance.image, pull=args.pull) if args.pin_images and instance.image else None
        )
        entries.append(
            entry(
                instance,
                prediction,
                dataset=args.dataset,
                split=args.split,
                revision=args.revision,
                image=image,
            )
        )
        tasks.append(Task(instance.instance_id, prediction.model, prediction.patch_sha256, sealed))
    args.out.mkdir(parents=True, exist_ok=True)
    tasks.sort(key=lambda t: (t.instance_id, t.model, t.patch_sha256))
    _write_jsonl(args.out / "sealed.jsonl", (task.row() for task in tasks))
    write_manifest(args.out / "manifest.jsonl", entries)
    sys.stdout.write(f"{len(tasks)} sealed inputs and their manifest in {args.out}\n")
    return 0


def _run_command(args: argparse.Namespace, extra: Sequence[str]) -> int:
    tasks = [Task.from_row(row) for row in read_jsonl(args.sealed)]
    env = dict(os.environ)
    if args.data:
        env["REPRO_DATA_DIR"] = str(args.data)
    if args.sandbox:
        env["REPRO_SANDBOX"] = args.sandbox
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("a", encoding="utf-8") as results:
        for task in tasks[: args.limit]:
            outcome = run_task(task, args.mirrors, args.out / "cards", env=env, extra=extra)
            results.write(json.dumps(asdict(outcome), sort_keys=True) + "\n")
            results.flush()
            sys.stdout.write(f"{task.instance_id} ({task.model}): {outcome.status}\n")
            sys.stdout.flush()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    given = list(sys.argv[1:] if argv is None else argv)
    extra = given[given.index("--") + 1 :] if "--" in given else []
    given = given[: given.index("--")] if "--" in given else given
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    sealing = commands.add_parser("seal", help="sealed inputs and a manifest from a dataset")
    sealing.add_argument("--instances", type=Path, required=True, help="SWE-format JSONL")
    sealing.add_argument("--predictions", type=Path, required=True, help="predictions JSONL")
    sealing.add_argument("--dataset", required=True, help="e.g. nebius/SWE-rebench")
    sealing.add_argument("--split", required=True)
    sealing.add_argument("--revision", required=True, help="the dataset's commit")
    sealing.add_argument("--out", type=Path, required=True)
    sealing.add_argument("--pin-images", action="store_true", help="record images by digest")
    sealing.add_argument("--pull", action="store_true", help="pull each image to pin it")
    running = commands.add_parser("run", help="repro run on sealed inputs")
    running.add_argument("--sealed", type=Path, required=True)
    running.add_argument("--mirrors", type=Path, required=True, help="bare mirrors, kept")
    running.add_argument("--out", type=Path, required=True)
    running.add_argument("--data", type=Path, help="Repro's data directory for these runs")
    running.add_argument("--sandbox", choices=("process", "docker"))
    running.add_argument("--limit", type=int)
    args = parser.parse_args(given)
    try:
        return _seal_command(args) if args.command == "seal" else _run_command(args, extra)
    except ContractError as exc:
        sys.stderr.write(f"repro_bench.swe: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
