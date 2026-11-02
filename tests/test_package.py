"""The package surface itself: exports and the version.

The version used to drift (``0.1.0`` in the package, ``0.3.0`` in
``pyproject.toml``); these tests pin the two together so a release cannot
ship a mismatched pair.
"""

from __future__ import annotations

import pathlib
import re

import esml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_every_exported_name_exists():
    missing = [name for name in esml.__all__ if not hasattr(esml, name)]
    assert missing == []


def test_the_version_matches_pyproject():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert match is not None, "pyproject.toml has no version"
    assert esml.__version__ == match.group(1)


def test_the_full_command_line_is_exported():
    for name in (
        "run_cli",
        "CLIResult",
        "check",
        "check_units",
        "tasks",
        "TaskResult",
        "TasksOutput",
        "inspect",
        "dump",
        "version",
        "solve",
        "simulate",
        "Session",
        "MAX_UNKNOWNS",
    ):
        assert name in esml.__all__, f"{name} is not exported"
        assert hasattr(esml, name)
