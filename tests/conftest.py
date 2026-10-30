"""Shared fixtures: an executable shim that runs the fake engine with this Python."""

from __future__ import annotations

import pathlib
import shlex
import sys

import pytest

from esml import Session

FAKE = pathlib.Path(__file__).with_name("fake_esml.py")


@pytest.fixture
def fake_bin(tmp_path: pathlib.Path) -> str:
    """A `esml`-named executable that dispatches to ``tests/fake_esml.py``."""
    shim = tmp_path / "esml"
    shim.write_text(
        "#!/bin/sh\nexec %s %s \"$@\"\n"
        % (shlex.quote(sys.executable), shlex.quote(str(FAKE)))
    )
    shim.chmod(0o755)
    return str(shim)


@pytest.fixture
def open_session(fake_bin, monkeypatch):
    """Factory: ``open_session(mode="ok", timeout=5)`` → a live fake session."""
    sessions = []

    def open_(mode: str = "ok", timeout: float = 5.0, **kwargs):
        monkeypatch.setenv("FAKE_ESML_MODE", mode)
        session = Session(
            "plant.esml", binary=fake_bin, timeout=timeout, **kwargs
        )
        sessions.append(session)
        return session

    yield open_

    for session in sessions:
        if not session.closed:
            session.close()
