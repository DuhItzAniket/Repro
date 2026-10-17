"""What a project is and what it needs, read from its files (D03). No network, no target code."""

import hashlib
import re
import shutil
import tomllib
from pathlib import Path

import pytest

from repro.provision import ProjectError, inspect_project
from repro.provision.project import chosen_groups, export_options

PROJECTS = Path(__file__).parent / "data" / "projects"
PINNED = ("iniconfig==2.0.0", "packaging==24.2", "pluggy==1.5.0", "pytest==8.3.3")


@pytest.mark.parametrize(
    ("kind", "source", "requirements", "build", "installable"),
    [
        ("uv", "uv.lock", ("colorama==0.4.6 ; sys_platform == 'win32'", *PINNED),
         ("hatchling==1.25.0", "editables~=0.3"), True),
        ("poetry", "poetry.lock", ('colorama==0.4.6; sys_platform == "win32"', *PINNED),
         ("poetry-core==1.9.1",), True),
        ("pdm", "pdm.lock", ('colorama==0.4.6; sys_platform == "win32"', *PINNED),
         ("pdm-backend==2.4.3",), True),
        ("requirements", "requirements.txt", ("iniconfig==2.0.0", "pytest==8.3.3"), (), False),
        ("setuptools", None, ("iniconfig==2.0.0", "pytest==8.3.3"), ("setuptools",), True),
    ],
)  # fmt: skip
def test_each_kind_of_project_is_read_from_its_files(
    kind: str,
    source: str | None,
    requirements: tuple[str, ...],
    build: tuple[str, ...],
    installable: bool,
) -> None:
    project = inspect_project(PROJECTS / kind)
    assert (project.kind, project.source) == (kind, source)
    assert project.requirements == requirements
    assert project.build_requires == build
    assert project.installable is installable
    expected = (
        hashlib.sha256((PROJECTS / kind / source).read_bytes()).hexdigest() if source else None
    )
    assert project.lock_sha256 == expected
    assert project.notes == ()


def make(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("calc @ https://example.com/calc-1.0.tar.gz", "a direct reference"),
        ("git+https://example.com/calc.git", "a direct reference"),
        ("calc @ file:///home/someone/calc", "a direct reference"),
        ("--index-url https://example.com/simple", "a pip option (--index-url)"),
        ("--extra-index-url https://example.com/simple", "a pip option (--extra-index-url)"),
        ("-e .", "a pip option (-e)"),
        ("--find-links ./wheels", "a pip option (--find-links)"),
    ],
)
def test_anything_but_the_index_is_refused(tmp_path: Path, line: str, why: str) -> None:
    root = make(tmp_path, {"requirements.txt": f"iniconfig==2.0.0\n{line}\n"})
    with pytest.raises(ProjectError, match=re.escape(f"is {why}")):
        inspect_project(root)


def test_a_requirements_include_must_stay_in_the_snapshot(tmp_path: Path) -> None:
    root = make(tmp_path / "project", {"requirements.txt": "-r ../outside.txt\n"})
    (tmp_path / "outside.txt").write_text("iniconfig\n", encoding="utf-8")
    with pytest.raises(ProjectError, match="outside the snapshot"):
        inspect_project(root)


def test_a_lock_package_from_elsewhere_is_refused(tmp_path: Path) -> None:
    lock = (PROJECTS / "poetry" / "poetry.lock").read_text(encoding="utf-8")
    lock += (
        '\n[[package]]\nname = "calc-extras"\nversion = "1.0"\n\n[package.source]\ntype = "git"\n'
    )
    root = make(tmp_path, {"pyproject.toml": "[tool.poetry]\n", "poetry.lock": lock})
    with pytest.raises(ProjectError, match="calc-extras comes from a git source"):
        inspect_project(root)


def test_setup_py_requirements_must_be_literals(tmp_path: Path) -> None:
    root = make(
        tmp_path, {"setup.py": "from setuptools import setup\nsetup(install_requires=REQS)\n"}
    )
    with pytest.raises(ProjectError, match="install_requires is not a literal list"):
        inspect_project(root)


def test_setup_cfg_and_pep_621_groups_are_read(tmp_path: Path) -> None:
    root = make(
        tmp_path,
        {
            "setup.cfg": "[options]\ninstall_requires =\n    iniconfig\n\n"
            "[options.extras_require]\ntesting =\n    pluggy\n",
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["packaging"]\n\n'
            '[dependency-groups]\ntest = ["pytest", {include-group = "other"}]\n',
        },
    )
    project = inspect_project(root)
    assert project.kind == "setuptools"
    assert project.requirements == ("packaging", "pytest", "iniconfig", "pluggy")
    assert project.build_requires == ("setuptools",)  # PEP 518's default


def test_what_the_metadata_declares_is_read_whatever_the_kind(tmp_path: Path) -> None:
    """F02: a requirements file need not list what ``[project]`` declares."""
    root = make(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["six>=1"]\n',
            "requirements-dev.txt": "pytest\n",
        },
    )
    project = inspect_project(root)
    assert (project.kind, project.requirements) == ("requirements", ("pytest",))
    assert (project.declared, project.declared_file) == (("six>=1",), "pyproject.toml")


@pytest.mark.parametrize(
    "files",
    [
        {"pyproject.toml": '[project]\nname = "x"\ndynamic = ["dependencies"]\n'},
        {"setup.py": "from setuptools import setup\nsetup(**CONFIG)\n"},
        {"setup.py": "from setuptools import setup\nsetup(install_requires=REQS)\n"},
        {"setup.py": "from setuptools import setup\nsetup(extras_require=EXTRAS)\n"},
        {"setup.cfg": "[options]\ninstall_requires = file: requirements.in\n"},
        {"pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.12"\nsix = "^1"\n'},
    ],
    ids=["dynamic", "kwargs", "not literal", "extras", "file directive", "poetry table"],
)
def test_metadata_that_cannot_be_read_statically_is_unknown(
    tmp_path: Path, files: dict[str, str]
) -> None:
    """Not an empty list: a dependency added there would go unseen (F02)."""
    project = inspect_project(make(tmp_path, {"requirements.txt": "pytest\n", **files}))
    assert project.declared is None


def test_pytest_is_added_when_the_project_does_not_declare_it(tmp_path: Path) -> None:
    root = make(tmp_path, {"requirements.txt": "iniconfig==2.0.0\n"})
    project = inspect_project(root)
    assert project.requirements == ("iniconfig==2.0.0", "pytest")
    assert project.notes == ("pytest added: the project does not declare it",)


def test_a_poetry_project_without_its_lock_is_resolved_and_noted(tmp_path: Path) -> None:
    shutil.copytree(PROJECTS / "poetry", tmp_path / "p")
    (tmp_path / "p" / "poetry.lock").unlink()
    project = inspect_project(tmp_path / "p")
    assert project.kind == "poetry"
    assert project.source is None
    assert "no poetry.lock: the declared dependencies are resolved instead" in project.notes


def test_a_lock_uv_cannot_export_is_reported(tmp_path: Path) -> None:
    root = make(tmp_path, {"pyproject.toml": '[project]\nname = "x"\n', "uv.lock": "not toml ["})
    with pytest.raises(ProjectError, match=r"uv\.lock cannot be exported"):
        inspect_project(root)


def test_only_what_the_tests_need_is_installed(tmp_path: Path) -> None:
    """H02: docs, typing and release groups are left out; ``dev`` only when no test group is."""
    pyproject = (
        '[project]\nname = "x"\ndependencies = ["packaging"]\n'
        '[project.optional-dependencies]\ntesting = ["pluggy"]\nserver = ["uvicorn"]\n\n'
        '[dependency-groups]\ntests = ["pytest"]\ndev = ["ruff", "tox"]\n'
        'docs = ["sphinx"]\ntyping = ["mypy"]\n'
    )
    project = inspect_project(make(tmp_path / "groups", {"pyproject.toml": pyproject}))
    assert project.requirements == ("packaging", "pluggy", "pytest")
    dev_only = pyproject.replace('tests = ["pytest"]\n', "").replace('testing = ["pluggy"]\n', "")
    project = inspect_project(make(tmp_path / "dev", {"pyproject.toml": dev_only}))
    assert project.requirements == ("packaging", "ruff", "tox", "pytest")
    assert export_options(tomllib.loads(pyproject)) == [
        "--no-default-groups", "--group", "tests", "--extra", "testing",
    ]  # fmt: skip
    assert chosen_groups(["docs", "dev"]) == ["dev"]
    assert chosen_groups(["docs"]) == []


def test_a_requirements_directory_adds_the_projects_own_dependencies(tmp_path: Path) -> None:
    """H02: pip-tools' ``requirements/tests.txt`` lists the test tools only."""
    root = make(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "x"\ndependencies = ["packaging>=24"]\n',
            "requirements/tests.txt": "freezegun==1.4.0\n    # via -r tests.in\npytest==8.1.1\n",
            "requirements/docs.txt": "sphinx==7.0.0\n",
        },
    )
    project = inspect_project(root)
    assert (project.kind, project.source) == ("requirements", "requirements/tests.txt")
    assert project.requirements == ("freezegun==1.4.0", "pytest==8.1.1", "packaging>=24")
