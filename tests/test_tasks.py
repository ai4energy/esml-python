"""Tests for the compute-task wrapper :func:`esml.tasks`.

The fake engine answers ``esml tasks --json`` with an ``esml.tasks/v1``
envelope; the failure modes (``ok: false``, a wrong apiVersion, non-JSON
output, a hang) are driven through ``FAKE_ESML_MODE``.
"""

from __future__ import annotations

import sys

import pytest

import esml  # noqa: F401  (loads the `esml.tasks` submodule)
from esml import EsmlError, EsmlProtocolError, EsmlTimeout, tasks

#: The submodule itself: `esml.tasks` at package level is the *function*
#: (it shadows the module), so the module is reached through sys.modules.
tasks_module = sys.modules["esml.tasks"]

TASKS_DOC = """<?xml version="1.0"?>
<esml xmlns="https://www.ai4energy.cn/esml/v1" name="Batch">
  <variableTypes><type name="real" unit="1" default="0"/></variableTypes>
  <modelTypes><modelType name="Decay">
    <parameters><parameter name="lam" type="real" default="0.5"/></parameters>
    <variables><variable name="x" type="real" role="state" initial="1.0"/></variables>
    <equations><equation>Der(x) = -lam * x</equation></equations>
  </modelType></modelTypes>
  <systems><system name="S"><instances><instance name="m" type="Decay"/></instances></system></systems>
  <computeTasks name="batch" target="S">
    <task name="sim1" kind="simulate"><tspan from="0" to="1"/><solver name="Tsit5" steps="10"/></task>
    <task name="fc1" kind="forecast"><tspan from="0" to="1"/></task>
  </computeTasks>
</esml>
"""

#: A compute-task document without any task — the engine has nothing to run.
EMPTY_DOC = "\n".join(
    line for line in TASKS_DOC.splitlines() if "<task " not in line
)


@pytest.fixture
def tasks_doc(tmp_path):
    path = tmp_path / "batch.esml"
    path.write_text(TASKS_DOC)
    return str(path)


@pytest.fixture
def empty_doc(tmp_path):
    path = tmp_path / "empty.esml"
    path.write_text(EMPTY_DOC)
    return str(path)


def test_tasks_returns_one_result_per_task(fake_bin, tasks_doc):
    out = tasks(tasks_doc, binary=fake_bin)
    assert len(out) == 2
    assert [t.name for t in out] == ["sim1", "fc1"]
    assert [t.kind for t in out] == ["simulate", "forecast"]
    assert out.tasks[0].target == "S"
    assert out.tasks[0].units == {}
    assert out.tasks[0].meta["engineVersion"] == "9.9.9-fake"
    assert out.tasks[0].outcome == {"kind": "simulate", "status": "ok"}
    assert out.raw["ok"] is True
    assert out.raw["apiVersion"] == "esml.tasks/v1"


def test_tasks_can_be_looked_up_by_name(fake_bin, tasks_doc):
    out = tasks(tasks_doc, binary=fake_bin)
    assert out.by_name("fc1").kind == "forecast"
    assert out.by_name("missing") is None


def test_tasks_raises_when_the_engine_exits_non_zero(fake_bin, tasks_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "error")
    with pytest.raises(EsmlError) as exc:
        tasks(tasks_doc, binary=fake_bin)
    assert exc.value.code == "tasks.failed"
    assert "fake engine failure" in str(exc.value)
    assert exc.value.raw["code"] == 1


def test_tasks_raises_when_the_engine_reports_a_failure(fake_bin, tasks_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "task-error")
    with pytest.raises(EsmlError) as exc:
        tasks(tasks_doc, binary=fake_bin)
    assert exc.value.op == "tasks"
    assert exc.value.code == "task.failed"
    assert "sim1" in str(exc.value)
    # The envelope stays reachable.
    assert exc.value.raw["apiVersion"] == "esml.tasks/v1"


def test_tasks_raises_when_the_document_has_no_task(fake_bin, empty_doc):
    with pytest.raises(EsmlError) as exc:
        tasks(empty_doc, binary=fake_bin)
    assert exc.value.code == "tasks.empty"


def test_tasks_rejects_an_unknown_api_version(fake_bin, tasks_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "bad-api")
    with pytest.raises(EsmlProtocolError) as exc:
        tasks(tasks_doc, binary=fake_bin)
    assert "esml.tasks/v1" in str(exc.value)


def test_tasks_rejects_output_that_is_not_json(fake_bin, tasks_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "bad-json")
    with pytest.raises(EsmlProtocolError):
        tasks(tasks_doc, binary=fake_bin)


def test_tasks_timeout_raises(fake_bin, tasks_doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "timeout")
    with pytest.raises(EsmlTimeout):
        tasks(tasks_doc, binary=fake_bin, timeout=0.5)


def test_tasks_passes_system_libraries_and_jobs_to_the_engine(
    fake_bin, tasks_doc, monkeypatch
):
    seen = {}
    real_run_cli = tasks_module.run_cli

    def spy(args, **kwargs):
        seen["args"] = list(args)
        return real_run_cli(args, **kwargs)

    monkeypatch.setattr(tasks_module, "run_cli", spy)
    tasks(tasks_doc, system="S", libraries=["/tmp/libroot"], jobs=4, binary=fake_bin)
    assert seen["args"] == [
        "tasks",
        tasks_doc,
        "--json",
        "--system",
        "S",
        "-L",
        "/tmp/libroot",
        "--jobs",
        "4",
    ]


@pytest.mark.parametrize("jobs", [0, -1, 1.5, True, "many"])
def test_tasks_rejects_a_bad_job_count(fake_bin, tasks_doc, jobs):
    with pytest.raises(ValueError):
        tasks(tasks_doc, jobs=jobs, binary=fake_bin)
