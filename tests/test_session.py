"""Protocol tests for the ESML Python client, against a faithful fake engine.

No real engine binary is needed: ``tests/fake_esml.py`` implements the
``esml.session/v1`` envelopes (open/solve/simulate/predict/params/state/
snapshot/restore/info/close and the error envelope). Integration tests against
the real binary live in ``test_integration.py`` and are skipped unless
``ESML_BIN`` is set.
"""

from __future__ import annotations

import math
import time

import pytest

from esml import (
    EsmlBinaryNotFound,
    EsmlClosed,
    EsmlError,
    EsmlProtocolError,
    EsmlTimeout,
    Session,
    find_binary,
)


def test_open_envelope_fields(open_session):
    s = open_session()
    assert s.doc_hash == 42
    assert s.system == "Fake"
    assert s.unknowns == 2
    assert s.dynamic is True
    assert s.engine_version == "9.9.9-fake"
    assert s.open_envelope["op"] == "open"


def test_solve_and_hot_param_update(open_session):
    s = open_session()
    first = s.solve()
    assert set(first.values) == {"m.x", "m.y"}
    assert first.values["m.x"] == pytest.approx(1.0 / 1.5)
    assert first.warm is False
    assert first.iterations == 5
    assert first.iterations is not None

    s.set_param("m.lam", 2.0)
    second = s.solve()
    assert second.values["m.x"] == pytest.approx(1.0 / 3.0)
    assert second.values["m.y"] == pytest.approx(2.0 / 3.0)
    assert second.warm is True
    assert second.iterations == 3


def test_set_params_mapping_and_pairs(open_session):
    s = open_session()
    s.set_params({"m.lam": 1.0})
    assert s.solve().values["m.x"] == pytest.approx(0.5)
    s.set_params([("m.lam", 3.0)])
    assert s.solve().values["m.x"] == pytest.approx(0.25)

    with pytest.raises(ValueError):
        s.set_params({})
    # Path names are the engine's to judge: the batch is sent and rejected
    # before anything is applied.
    with pytest.raises(EsmlError):
        s.set_params([("m.missing", 1.0)])
    assert s.solve().values["m.x"] == pytest.approx(0.25)


def test_simulate_window_observe_and_chaining(open_session):
    s = open_session()
    first = s.simulate((0.0, 2.0), steps=4, observe=["m.y"])
    assert first.steps == 4
    assert len(first.t) == 5
    assert list(first.series) == ["m.y"]
    assert first.series["m.y"][0] == pytest.approx(0.5)
    assert first.continued is False

    chained = s.simulate((2.0, 3.0), steps=2, observe=["m.x"])
    assert chained.continued is True
    assert chained.series["m.x"][0] == pytest.approx(first.series["m.y"][-1] / 0.5)

    s.clear_state()
    fresh = s.simulate((2.0, 3.0), steps=2, observe=["m.x"])
    assert fresh.continued is False
    assert fresh.series["m.x"][0] == pytest.approx(1.0)


def test_simulate_observe_defaults_to_all_variables(open_session):
    s = open_session()
    traj = s.simulate((0.0, 1.0), steps=2)
    assert list(traj.series) == ["m.x", "m.y"]


def test_predict_does_not_advance_the_session(open_session):
    s = open_session()
    p = s.predict(1.0, steps=2, observe=["m.x"])
    assert [round(t, 12) for t in p.t] == [0.0, 0.5, 1.0]
    assert p.continued is False

    traj = s.simulate((0.0, 1.0), steps=2, observe=["m.x"])
    # If predict had advanced the session this window would be `continued`.
    assert traj.continued is False


def test_state_injection_and_info(open_session):
    s = open_session()
    s.set_state("m.x", 2.0)
    info = s.info()
    assert info.pending_states == 1
    assert info.dynamic is True
    assert info.doc_hash == 42
    assert s.solve().values["m.x"] == pytest.approx(2.0 / 1.5)

    s.clear_state()
    assert s.info().pending_states == 0

    # `m.y` is algebraic, not a dynamic state.
    with pytest.raises(EsmlError):
        s.set_state("m.y", 1.0)


def test_set_states_batch(open_session):
    s = open_session()
    s.set_states({"m.x": 3.0})
    assert s.info().pending_states == 1
    assert s.solve().values["m.x"] == pytest.approx(3.0 / 1.5)
    with pytest.raises(ValueError):
        s.set_states([])


def test_snapshot_restore_roundtrip(open_session):
    s = open_session()
    s.set_params({"m.lam": 1.5})
    s.simulate((0.0, 1.0), steps=2, observe=["m.x"])
    snap = s.snapshot()
    assert snap["docHash"] == 42
    assert snap["params"] == [["m.lam", 1.5]]

    s.set_param("m.lam", 0.25)
    s.clear_state()
    s.restore(snap)

    assert s.snapshot()["params"] == [["m.lam", 1.5]]
    # The chained end was restored, so the next window continues at t=1.
    traj = s.simulate((1.0, 2.0), steps=2, observe=["m.x"])
    assert traj.continued is True

    with pytest.raises(TypeError):
        s.restore("not a snapshot mapping")  # type: ignore[arg-type]
    with pytest.raises(EsmlError):
        s.restore(dict(snap, docHash=7))


def test_engine_error_carries_op_message_and_raw_envelope(open_session):
    s = open_session()
    with pytest.raises(EsmlError) as excinfo:
        s.set_param("m.missing", 1.0)
    err = excinfo.value
    assert err.op == "set_param"
    assert "not a declared parameter" in str(err)
    assert err.raw["op"] == "error"
    assert err.raw["request"] == "set_param"
    # An engine-side error does not desynchronize the session.
    assert s.solve().values["m.x"] == pytest.approx(1.0 / 1.5)


def test_observe_rejected_by_engine(open_session):
    s = open_session()
    with pytest.raises(EsmlError):
        s.simulate((0.0, 1.0), steps=1, observe=["m.lam"])
    with pytest.raises(EsmlError):
        s.simulate((0.0, 1.0), steps=1, observe=["m.x", "m.x"])


def test_client_rejects_malformed_input_before_sending(open_session):
    s = open_session()
    with pytest.raises(ValueError):
        s.set_param("m.lam", math.nan)
    with pytest.raises(ValueError):
        s.set_param("m.lam", math.inf)
    with pytest.raises(ValueError):
        s.set_params({"m.lam": math.nan})
    with pytest.raises(ValueError):
        s.simulate((0.0, math.nan))
    with pytest.raises(ValueError):
        s.simulate((0.0, 1.0), observe=[])
    with pytest.raises(ValueError):
        s.simulate((0.0, 1.0), steps=0)
    with pytest.raises(ValueError):
        s.predict(0.0)
    with pytest.raises(ValueError):
        s.predict(-1.0)
    with pytest.raises(ValueError):
        s.set_state("m.x", math.nan)
    # None of the rejected calls consumed an envelope: the session still works.
    assert s.info().doc_hash == 42


def test_simulate_rejects_bad_steps(open_session):
    s = open_session()
    with pytest.raises(ValueError):
        s.simulate((0.0, 1.0), steps=0)
    assert s.solve().values["m.x"] == pytest.approx(1.0 / 1.5)


def test_close_is_idempotent_and_ops_after_close_raise(open_session):
    s = open_session()
    s.close()
    s.close()
    assert s.closed
    with pytest.raises(EsmlClosed):
        s.solve()
    with pytest.raises(EsmlClosed):
        s.set_param("m.lam", 1.0)


def test_context_manager_closes(open_session):
    s = open_session()
    with s:
        assert s.solve().values["m.x"] == pytest.approx(1.0 / 1.5)
    assert s.closed


def test_bad_api_version_raises_protocol_error(open_session):
    with pytest.raises(EsmlProtocolError) as excinfo:
        open_session(mode="bad-version")
    assert "apiVersion" in str(excinfo.value)


def test_engine_crash_raises_closed(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "crash")
    s = Session("plant.esml", binary=fake_bin, timeout=2.0)
    try:
        with pytest.raises(EsmlClosed) as excinfo:
            s.info()
        assert "exited" in str(excinfo.value)
        assert s.closed
    finally:
        s.close()


def test_timeout_kills_the_engine(fake_bin, monkeypatch):
    monkeypatch.setenv("FAKE_ESML_MODE", "silent")
    s = Session("plant.esml", binary=fake_bin, timeout=0.3)
    started = time.monotonic()
    with pytest.raises(EsmlTimeout):
        s.info()
    assert time.monotonic() - started < 5.0
    assert s.closed
    s.close()


def test_non_json_output_raises_protocol_error(open_session):
    s = open_session(mode="garbage")
    with pytest.raises(EsmlProtocolError):
        s.solve()
    assert s.closed


def test_find_binary_explicit_missing_path_is_loud(tmp_path):
    missing = tmp_path / "esml"
    with pytest.raises(EsmlBinaryNotFound):
        find_binary(missing)


def test_find_binary_bad_esml_bin_env_is_loud(tmp_path, monkeypatch):
    monkeypatch.setenv("ESML_BIN", str(tmp_path / "missing"))
    with pytest.raises(EsmlBinaryNotFound):
        find_binary()


def test_find_binary_explicit_wins_over_env(fake_bin, monkeypatch):
    monkeypatch.setenv("ESML_BIN", "/definitely/not/here")
    assert find_binary(fake_bin) == fake_bin
