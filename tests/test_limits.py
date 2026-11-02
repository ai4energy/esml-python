"""The academic edition's unknown limit (16,384).

The limit lives in the engine; the client's job is to make the refusal
legible — with the right kind and a message that names both the limit and
the edition that lifts it.  These tests drive the real client code path
(one-shot ``solve``) against the fake engine, which reports its unknown
count through ``FAKE_ESML_UNKNOWNS``.
"""

from __future__ import annotations

import pytest

from esml import EsmlError, MAX_UNKNOWNS, simulate, solve

DOC = """<?xml version="1.0"?>
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


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "decay.esml"
    path.write_text(DOC)
    return str(path)


def test_the_limit_is_sixteen_thousand_384():
    assert MAX_UNKNOWNS == 16_384


def test_solve_at_the_limit_is_allowed(fake_bin, doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_UNKNOWNS", str(MAX_UNKNOWNS))
    out = solve(doc, binary=fake_bin)
    assert out.unknowns == MAX_UNKNOWNS
    assert out.values["m.x"] == pytest.approx(1.0 / 1.5)


def test_solve_above_the_limit_raises_academic_limit(fake_bin, doc, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_UNKNOWNS", str(MAX_UNKNOWNS + 1))
    with pytest.raises(EsmlError) as exc:
        solve(doc, binary=fake_bin)
    assert exc.value.code == "academic_limit"
    assert exc.value.kind == "academic_limit"
    assert exc.value.op == "solve"
    # The message must name the limit and the edition that lifts it.
    assert "学术版上限 16384" in str(exc.value)
    assert "商业版请用商业二进制/客户端" in str(exc.value)
    assert str(MAX_UNKNOWNS + 1) in str(exc.value)


def test_simulate_is_not_blocked_by_the_client(fake_bin, doc, monkeypatch):
    # `esml simulate` reports no total unknown count, so the client cannot
    # judge it here — the academic engine refuses such a model itself when
    # it flattens it.  The client must not invent a verdict here either.
    monkeypatch.setenv("FAKE_ESML_UNKNOWNS", str(MAX_UNKNOWNS + 1))
    traj = simulate(doc, (0.0, 1.0), 20, observe=["m.x"], binary=fake_bin)
    assert traj.steps == 20
    assert len(traj.t) == 21
    assert traj.series["m.x"][0] == pytest.approx(1.0, rel=1e-9)
