"""Versioned prompt files (G02).

Each prompt is a Markdown file in this directory, ``<name>.md``, that opens with its version::

    ---
    version: 3
    ---
    The prompt's text, with $placeholders filled in when it is rendered.

A call names its prompt as ``<name>/<version>`` (``AgentRequest.prompt_version``): cassettes are
keyed by it and evaluation results are reported against it. So that a version always means one
text, ``lock.json`` holds the SHA-256 of every version's text. A file whose text no longer
matches its version's entry was changed without a new version; a version with no entry has not
been locked. Entries are only ever added: a version, once locked, keeps its digest, so old
cassettes and results keep naming a text that existed.

Placeholders are ``string.Template``'s (``$name``, ``${name}``, ``$$`` for a dollar sign).
Rendering fills them in once: what is substituted is never read for placeholders again, so
untrusted text cannot reach into the template.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Final

#: This package's own prompts.
PROMPTS_DIR: Final = Path(__file__).parent
LOCK_FILE: Final = "lock.json"
NAME: Final = re.compile(r"[a-z][a-z0-9_-]{0,47}")
FRONT_MATTER: Final = re.compile(r"---\nversion: ([1-9][0-9]{0,5})\n---\n")


class PromptError(ValueError):
    """A prompt file that cannot be used, or a rendering that does not fit it."""


@dataclass(frozen=True, slots=True)
class Prompt:
    name: str
    version: int
    text: str

    @property
    def prompt_version(self) -> str:
        """``<name>/<version>``: what a call built from this prompt names."""
        return f"{self.name}/{self.version}"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(Template(self.text).get_identifiers())

    def render(self, values: Mapping[str, str]) -> str:
        """The text with every placeholder filled in; exactly its placeholders are given."""
        missing = sorted(self.placeholders - set(values))
        extra = sorted(set(values) - self.placeholders)
        if missing or extra:
            raise PromptError(
                f"{self.prompt_version}: missing {missing or 'none'}, unknown {extra or 'none'}"
            )
        return Template(self.text).substitute(values)


def read_prompt(path: Path) -> Prompt:
    """A prompt file: its name from the file, its version from the front matter."""
    name = path.stem
    if path.suffix != ".md" or not NAME.fullmatch(name):
        raise PromptError(f"{path.name}: a prompt file is <lowercase name>.md")
    data = path.read_bytes()
    if b"\r" in data:
        raise PromptError(f"{path.name}: prompt files use LF line endings")
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        raise PromptError(f"{path.name}: not UTF-8") from None
    front = FRONT_MATTER.match(content)
    if front is None:
        raise PromptError(f"{path.name}: must open with ---, version: <n>, ---")
    prompt = Prompt(name, int(front.group(1)), content[front.end() :])
    if not Template(prompt.text).is_valid():
        raise PromptError(f"{path.name}: a $ that is not a placeholder (write $$ for a dollar)")
    return prompt


def load_prompt(name: str, directory: Path = PROMPTS_DIR) -> Prompt:
    """The prompt called ``name``; it must be locked at its version."""
    prompt = read_prompt(directory / f"{name}.md")
    locked = read_lock(directory).get(prompt.prompt_version)
    if locked != prompt.sha256:
        raise PromptError(f"{prompt.prompt_version} is not locked at its text: {lock_hint()}")
    return prompt


def prompts(directory: Path = PROMPTS_DIR) -> list[Prompt]:
    return [read_prompt(path) for path in sorted(directory.glob("*.md"))]


def read_lock(directory: Path = PROMPTS_DIR) -> dict[str, str]:
    path = directory / LOCK_FILE
    if not path.exists():
        return {}
    lock: dict[str, str] = json.loads(path.read_bytes())
    return lock


def lock_hint() -> str:
    return "a changed prompt needs a new version; lock new versions with pytest --update-goldens"


def lock_problems(directory: Path = PROMPTS_DIR) -> list[str]:
    """What is wrong between the prompt files and the lock: an empty list if nothing."""
    lock = read_lock(directory)
    problems = []
    for prompt in prompts(directory):
        locked = lock.get(prompt.prompt_version)
        if locked is None:
            problems.append(f"{prompt.prompt_version} is not locked")
        elif locked != prompt.sha256:
            problems.append(f"{prompt.prompt_version} changed since it was locked")
    return problems


def lock_new_versions(directory: Path = PROMPTS_DIR) -> list[str]:
    """Adds every unlocked version to the lock and returns them. A locked version whose text
    changed is refused: it needs a new version, not a new digest."""
    changed = [p for p in lock_problems(directory) if p.endswith("changed since it was locked")]
    if changed:
        raise PromptError(f"{'; '.join(changed)}: give each a new version")
    lock = read_lock(directory)
    added = [p.prompt_version for p in prompts(directory) if p.prompt_version not in lock]
    for prompt in prompts(directory):
        lock.setdefault(prompt.prompt_version, prompt.sha256)
    text = json.dumps(dict(sorted(lock.items())), indent=2) + "\n"
    (directory / LOCK_FILE).write_bytes(text.encode("utf-8"))
    return added
