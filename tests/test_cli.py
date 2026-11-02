"""Tests for the unrestricted CLI entry point :func:`esml.run_cli`.

No real engine binary is needed: ``tests/fake_esml.py`` answers the
one-shot subcommands (``echo-argv`` is a probe that reports exactly what
the client passed on the command line).
"""

from __future__ import annotations

import json

import pytest

import esml.cli as cli_module
from esml import (
    CLIResult,
    EsmlError,
    EsmlProtocolError,
    EsmlTimeout,
    check,
    check_units,
    dump,
    inspect,
    run_cli,
    version,
)

GOOD_DOC = """<?xml version="1.0"?>
<esml xmlns="https://www.ai4energy.cn/esml/v1" name="Decay">
  <variableTypes><type name="real" unit="1" default="0"/></variableTypes>
  <modelTypes><modelType name="Decay">
    <parameters><parameter name="lam" type="real" default="0.5"/></parameters>
    <variables><variable name="x" type="real" role="state" initial="1.0"/></variables>
    <equations><equation>Der(x) = -lam * x</equation></equations>
  </modelType></modelTypes>
  <systems><system name="S"><instances><instance name="m" type="Decay"/></instances></system></systems>
</esml>
"""

#: The same document with its root element left open — the validator's
#: "not well formed" case, i.e. the bad example that must go red.
BROKEN_DOC = GOOD_DOC.replace("</esml>", "")


@pytest.fixture
def good_doc(tmp_path):
    path = tmp_path / "good.esml"
    path.write_text(GOOD_DOC)
    return str(path)


@pytest.fixture
def broken_doc(tmp_path):
    path = tmp_path / "broken.esml"
    path.write_text(BROKEN_DOC)
    return str(path)


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


# ── the front validators ─────────────────────────────────────────────────


def test_check_returns_the_report_array(fake_bin, good_doc):
    reports = check(good_doc, binary=fake_bin)
    assert isinstance(reports, list)
    assert len(reports) == 1
    report = reports[0]
    assert report["file"] == good_doc
    assert report["well_formed"] is True
    assert report["summary"]["errors"] == 0
    assert report["findings"] == []


def test_check_raises_on_a_broken_document(fake_bin, broken_doc):
    with pytest.raises(EsmlError) as exc:
        check(broken_doc, binary=fake_bin)
    assert exc.value.op == "check"
    assert exc.value.code == "check.failed"
    # The message names the finding, and the report stays reachable.
    assert "XML" in str(exc.value)
    assert exc.value.raw["reports"][0]["summary"]["errors"] == 1


def test_check_raises_when_the_document_cannot_be_read(fake_bin):
    with pytest.raises(EsmlError) as exc:
        check("/nonexistent/decay.esml", binary=fake_bin)
    assert "read" in str(exc.value)


def test_check_units_returns_the_report_array(fake_bin, good_doc):
    reports = check_units(good_doc, binary=fake_bin)
    assert len(reports) == 1
    assert reports[0]["summary"]["type_unit_decls"] == 1
    assert reports[0]["summary"]["errors"] == 0


def test_check_units_raises_on_a_broken_document(fake_bin, broken_doc):
    with pytest.raises(EsmlError) as exc:
        check_units(broken_doc, binary=fake_bin)
    assert exc.value.op == "check-units"
    assert exc.value.raw["reports"][0]["well_formed"] is False


def test_check_units_fails_on_error_findings_even_with_exit_zero(fake_bin, broken_doc):
    # The engine's `check-units --json` path always exits 0, so the client
    # has to read the report's own verdict — otherwise a broken document
    # would look "checked".
    res = run_cli(["check-units", broken_doc, "--json"], binary=fake_bin)
    assert res.code == 0
    with pytest.raises(EsmlError) as exc:
        check_units(broken_doc, binary=fake_bin)
    assert "error finding" in str(exc.value)


def test_check_rejects_output_that_is_not_json(fake_bin, good_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "bad-json")
    with pytest.raises(EsmlProtocolError):
        check(good_doc, binary=fake_bin)


def test_check_timeout_raises(fake_bin, good_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "timeout")
    with pytest.raises(EsmlTimeout):
        check(good_doc, binary=fake_bin, timeout=0.5)


def test_check_passes_the_library_roots_to_the_engine(fake_bin, good_doc, monkeypatch):
    seen = {}
    real_run_cli = cli_module.run_cli

    def spy(args, **kwargs):
        seen["args"] = list(args)
        return real_run_cli(args, **kwargs)

    monkeypatch.setattr(cli_module, "run_cli", spy)
    check(good_doc, libraries=["/tmp/libroot"], binary=fake_bin)
    assert seen["args"] == ["check", good_doc, "--json", "-L", "/tmp/libroot"]


# ── the structural report, the dump and the version ─────────────────────


def test_inspect_returns_the_report_text(fake_bin, good_doc):
    text = inspect(good_doc, binary=fake_bin)
    assert "system   : S" in text
    assert "unknowns" in text


def test_dump_returns_the_flattened_listing(fake_bin, good_doc):
    text = dump(good_doc, binary=fake_bin)
    assert "system : S" in text
    assert "x = 1.0" in text


def test_inspect_raises_on_a_non_zero_exit(fake_bin, good_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "error")
    with pytest.raises(EsmlError) as exc:
        inspect(good_doc, binary=fake_bin)
    assert exc.value.op == "inspect"
    assert "fake engine failure" in str(exc.value)


def test_dump_raises_on_a_non_zero_exit(fake_bin, good_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "error")
    with pytest.raises(EsmlError) as exc:
        dump(good_doc, binary=fake_bin)
    assert exc.value.op == "dump"


def test_inspect_and_dump_pass_the_system_and_the_library_roots(
    fake_bin, good_doc, monkeypatch
):
    seen = []
    real_run_cli = cli_module.run_cli

    def spy(args, **kwargs):
        seen.append(list(args))
        return real_run_cli(args, **kwargs)

    monkeypatch.setattr(cli_module, "run_cli", spy)
    inspect(good_doc, system="S", libraries=["/tmp/libroot"], binary=fake_bin)
    dump(good_doc, system="S", libraries=["/tmp/libroot"], binary=fake_bin)
    assert seen == [
        ["inspect", good_doc, "--system", "S", "-L", "/tmp/libroot"],
        ["dump", good_doc, "--system", "S", "-L", "/tmp/libroot"],
    ]


def test_version_reads_the_engine_version(fake_bin):
    assert version(binary=fake_bin) == "9.9.9-fake"
