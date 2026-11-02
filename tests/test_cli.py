"""Tests for the unrestricted CLI entry point :func:`esml.run_cli`.

No real engine binary is needed: ``tests/fake_esml.py`` answers the
one-shot subcommands (``echo-argv`` is a probe that reports exactly what
the client passed on the command line).
"""

from __future__ import annotations

import json

import pytest

from esml import CLIResult, EsmlTimeout, run_cli


def test_run_cli_returns_stdout_stderr_and_code(fake_bin):
    res = run_cli(["echo-argv", "hello"], binary=fake_bin)
    assert isinstance(res, CLIResult)
    assert res.code == 0
    assert res.ok is True
    assert "hello" in res.stdout
    assert res.stderr == ""


def test_run_cli_passes_the_arguments_through_verbatim(fake_bin):
    res = run_cli(
        ["echo-argv", "check", "plant.esml", "--json", "-L", "/tmp/libroot"],
        binary=fake_bin,
    )
    payload = json.loads(res.stdout)
    assert payload["cmd"] == "echo-argv"
    assert payload["args"] == [
        "check",
        "plant.esml",
        "--json",
        "-L",
        "/tmp/libroot",
    ]


def test_run_cli_forwards_stdin(fake_bin):
    res = run_cli(["echo-argv"], input="payload on stdin", binary=fake_bin)
    assert json.loads(res.stdout)["stdin"] == "payload on stdin"


def test_run_cli_does_not_raise_on_a_non_zero_exit(fake_bin):
    res = run_cli(["check", "/nonexistent/plant.esml"], binary=fake_bin)
    assert res.code == 1
    assert res.ok is False
    assert "error:" in res.stderr


def test_run_cli_timeout_raises_esml_timeout(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "timeout")
    with pytest.raises(EsmlTimeout) as exc:
        run_cli(["check", "plant.esml"], binary=fake_bin, timeout=0.5)
    assert "0.5s" in str(exc.value)


def test_run_cli_honours_the_esml_bin_environment_variable(fake_bin, monkeypatch):
    monkeypatch.setenv("ESML_BIN", fake_bin)
    res = run_cli(["echo-argv"], binary=None)
    assert res.code == 0


def test_run_cli_reports_the_binary_it_ran(fake_bin):
    res = run_cli(["echo-argv"], binary=fake_bin)
    assert res.args[0] == fake_bin
    assert res.args[1] == "echo-argv"
