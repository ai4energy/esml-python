"""End-to-end tests against a **real** ESML engine binary.

Skipped unless ``ESML_BIN`` points at an executable ``esml``:

    ESML_BIN=/path/to/esml pytest -q

The model is ``tests/data/decay.esml``: ``Der(x) = -lam * x``, x(0) = 1.0,
``lam = 0.5``, so x(t) = exp(-lam * t).
"""

from __future__ import annotations

import math
import os
import pathlib

import pytest

from esml import EsmlError, Session, simulate as simulate_oneshot, solve as solve_oneshot

BIN = os.environ.get("ESML_BIN")
DATA = pathlib.Path(__file__).with_name("data") / "decay.esml"

pytestmark = pytest.mark.skipif(
    not BIN, reason="set ESML_BIN to a real `esml` binary to run integration tests"
)


@pytest.fixture
def session():
    with Session(DATA, system="S", binary=BIN, timeout=120.0) as s:
        yield s


def test_open_reports_the_document(session):
    assert session.dynamic is True
    assert session.doc_hash
    assert session.unknowns >= 1


def test_session_solve_carries_meta(session):
    out = session.solve()
    assert out.meta["converged"] is True
    assert out.meta["engineVersion"]
    assert isinstance(out.meta["docHash"], str)
    assert out.units == {}
    assert out.iterations is not None
    assert out.meta["residual"] <= out.meta["residualTolerance"]


def test_simulate_matches_the_analytic_decay(session):
    traj = session.simulate((0.0, 1.0), steps=20, observe=["m.x"])
    assert traj.points == 21
    assert list(traj.series) == ["m.x"]
    assert traj.series["m.x"][0] == pytest.approx(1.0, rel=1e-6)
    assert traj.series["m.x"][-1] == pytest.approx(math.exp(-0.5), rel=2e-3)
    assert traj.continued is False
    assert traj.doc_hash is not None
    assert traj.duration_ms is not None
    assert traj.meta["engineVersion"]
    assert isinstance(traj.meta["docHash"], str)
    assert traj.units == {}


def test_hot_parameter_update_changes_the_trajectory(session):
    session.clear_state()
    session.set_param("m.lam", 0.2)
    traj = session.simulate((0.0, 1.0), steps=20, observe=["m.x"])
    assert traj.series["m.x"][-1] == pytest.approx(math.exp(-0.2), rel=2e-3)


def test_observe_rejects_parameters_and_duplicates(session):
    with pytest.raises(EsmlError):
        session.simulate((0.0, 1.0), steps=2, observe=["m.lam"])
    with pytest.raises(EsmlError):
        session.simulate((0.0, 1.0), steps=2, observe=["m.x", "m.x"])
    # Rejected observations did not advance the session.
    assert session.info().sim_calls == 0


def test_predict_does_not_commit(session):
    session.clear_state()
    first = session.simulate((0.0, 1.0), steps=10, observe=["m.x"])
    p = session.predict(0.5, steps=5, observe=["m.x"])
    # A prediction starts from the session's current (chained) state — but it
    # must not commit that state.
    assert p.continued is True
    assert p.t[0] == 0.0
    assert p.series["m.x"][0] == pytest.approx(first.series["m.x"][-1], rel=1e-6)

    chained = session.simulate((1.0, 2.0), steps=10, observe=["m.x"])
    assert chained.continued is True
    assert chained.series["m.x"][0] == pytest.approx(first.series["m.x"][-1], rel=1e-6)


def test_oneshot_error_contract():
    with pytest.raises(EsmlError) as exc:
        solve_oneshot("/tmp/esml-missing-for-client.esml")
    assert exc.value.code == "io.read"
    assert exc.value.hint
    assert exc.value.doc_hash is None

    bad = DATA.read_text().replace("Der(x) = -lam * x", "Der(x) = 1")
    path = DATA.parent / "no-steady.tmp.esml"
    try:
        path.write_text(bad)
        with pytest.raises(EsmlError) as exc:
            solve_oneshot(path, system="S", binary=BIN)
        assert exc.value.code == "solve.failed"
        assert isinstance(exc.value.doc_hash, str)
        assert len(exc.value.doc_hash) == 64
    finally:
        path.unlink(missing_ok=True)


def test_oneshot_solve_and_simulate():
    steady = solve_oneshot(DATA, system="S", binary=BIN)
    assert steady.values["m.x"] == pytest.approx(0.0, abs=1e-8)
    assert steady.unknowns == 1
    assert steady.meta["converged"] is True
    assert isinstance(steady.meta["docHash"], str)
    assert len(steady.meta["docHash"]) == 64
    assert steady.meta["engineVersion"]
    assert steady.meta["unitCoverage"]["total"] == 1
    assert steady.meta["unitCoverage"]["complete"] is False
    assert steady.meta["iterations"] >= 1
    assert steady.meta["residual"] <= steady.meta["residualTolerance"]
    assert steady.units == {}

    traj = simulate_oneshot(DATA, (0.0, 1.0), 20, observe=["m.x"], system="S", binary=BIN)
    assert traj.steps == 20
    assert list(traj.series) == ["m.x"]
    assert traj.series["m.x"][0] == pytest.approx(1.0, rel=1e-6)
    assert traj.series["m.x"][-1] == pytest.approx(math.exp(-0.5), rel=2e-3)
    assert traj.meta["engineVersion"]
    assert isinstance(traj.meta["docHash"], str)
    assert len(traj.meta["docHash"]) == 64
    assert traj.meta["unitCoverage"]["complete"] is False
    assert traj.units == {}


def test_snapshot_restores_into_a_fresh_session(session):
    session.clear_state()
    session.set_param("m.lam", 0.3)
    first = session.simulate((0.0, 1.0), steps=10, observe=["m.x"])
    snap = session.snapshot()
    assert snap["docHash"] == session.doc_hash
    assert dict(snap["params"])["m.lam"] == pytest.approx(0.3)

    with Session(DATA, system="S", binary=BIN, timeout=120.0) as other:
        other.restore(snap)
        assert other.snapshot()["params"] == snap["params"]
        chained = other.simulate((1.0, 2.0), steps=10, observe=["m.x"])
        assert chained.continued is True
        assert chained.series["m.x"][0] == pytest.approx(
            first.series["m.x"][-1], rel=1e-6
        )
