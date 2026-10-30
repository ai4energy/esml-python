"""Resident ESML session (DTIL) over the `esml session` JSON protocol.

The client launches *only* the engine binary as a child process and speaks one
JSON envelope per line (`esml.session/v1`). Nothing is linked into Python, so
this package stays pure MIT while the engine binary keeps its own license.

Example
-------
>>> with Session("tank.esml", system="S") as s:
...     s.set_param("g.Q1", 10.0)
...     out = s.solve()
...     traj = s.simulate((0.0, 60.0), steps=30, observe=["g.T1"])
"""

from __future__ import annotations

import json
import math
import os
import queue
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .binary import engine_version, find_binary
from .errors import EsmlClosed, EsmlError, EsmlProtocolError, EsmlTimeout

_API = "esml.session/v1"


@dataclass
class SolveResult:
    """Result of :meth:`Session.solve` (a steady-state fixed point)."""

    values: dict
    iterations: Optional[int]
    warm: Optional[bool]
    unknowns: Optional[int]
    duration_ms: Optional[int]
    doc_hash: Optional[int]
    raw: dict
    units: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class Trajectory:
    """Result of :meth:`Session.simulate` / :meth:`Session.predict`."""

    t: list
    series: dict
    steps: int
    points: Optional[int]
    continued: bool
    duration_ms: Optional[int]
    doc_hash: Optional[int]
    raw: dict
    units: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class Info:
    """Result of :meth:`Session.info` (a session status snapshot)."""

    doc_hash: Optional[int]
    unknowns: Optional[int]
    cold_solves: Optional[int]
    warm_solves: Optional[int]
    last_iters: Optional[int]
    closed: Optional[bool]
    dynamic: Optional[bool]
    pending_states: Optional[int]
    sim_calls: Optional[int]
    last_steps: Optional[int]
    raw: dict
    source_hash: Optional[str] = None
    engine_version: Optional[str] = None


class Session:
    """A resident engine session.

    Parameters
    ----------
    path:
        Path to the ESML document.
    system:
        System name; omitted ⇒ the engine picks the document's system.
    libraries:
        Extra library roots passed as ``-L``.
    binary:
        Explicit path to the ``esml`` executable (otherwise ``$ESML_BIN`` or
        ``PATH``).
    timeout:
        Per-op timeout in seconds (``None`` = wait forever). On timeout the
        engine process is killed and :class:`EsmlTimeout` is raised.
    extra_args:
        Additional flags appended to the ``esml session`` command line.
    """

    def __init__(
        self,
        path: str | os.PathLike,
        *,
        system: Optional[str] = None,
        libraries: Sequence[str | os.PathLike] = (),
        binary: Optional[str | os.PathLike] = None,
        timeout: Optional[float] = None,
        extra_args: Sequence[str] = (),
    ) -> None:
        self.binary = find_binary(binary)
        self.engine_version = engine_version(self.binary)
        self.timeout = timeout
        args = [self.binary, "session", os.fspath(path)]
        if system:
            args += ["--system", system]
        for lib in libraries:
            args += ["-L", os.fspath(lib)]
        args += list(extra_args)
        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._closed = False
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._stderr: list[str] = []
        self._reader = threading.Thread(target=self._read_stdout, name="esml-stdout", daemon=True)
        self._err_reader = threading.Thread(
            target=self._read_stderr, name="esml-stderr", daemon=True
        )
        self._reader.start()
        self._err_reader.start()

        open_env = self._read_envelope()
        if open_env.get("op") == "error":
            self._kill()
            raise EsmlError(
                str(open_env.get("error")),
                op="open",
                request=open_env.get("request"),
                raw=open_env,
                code=open_env.get("code"),
                hint=open_env.get("hint"),
            )
        if open_env.get("op") != "open":
            self._kill()
            raise EsmlProtocolError(
                f"expected an `open` envelope, got `{open_env.get('op')!r}`", raw=open_env
            )
        self.open_envelope = open_env
        self.doc_hash = open_env.get("docHash")
        self.source_hash = open_env.get("sourceHash")
        self.system = open_env.get("system")
        self.unknowns = open_env.get("unknowns")
        self.dynamic = open_env.get("dynamic")

    # ── lifecycle ──────────────────────────────────────────────────────────
    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - defensive only
        try:
            if not self._closed:
                self._kill()
        except Exception:
            pass

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Close the session and stop the engine process (idempotent)."""
        with self._lock:
            if self._closed:
                return
            graceful = False
            try:
                self._write({"op": "close"})
                graceful = self._read_envelope().get("op") == "close"
            except EsmlError:
                graceful = False
            self._closed = True
        if not graceful:
            # The handshake failed, so the process is not following the
            # protocol; do not wait for it.
            self._kill()
            return
        try:
            self._proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._kill()

    # ── ops ────────────────────────────────────────────────────────────────
    def solve(self) -> SolveResult:
        """Solve the current parameters' steady-state fixed point."""
        env = self._request("solve")
        values = {row["path"]: row["value"] for row in env.get("values", [])}
        return SolveResult(
            values=values,
            iterations=env.get("iterations"),
            warm=env.get("warm"),
            unknowns=env.get("unknowns"),
            duration_ms=env.get("durationMs"),
            doc_hash=env.get("docHash"),
            raw=env,
            units=dict(env.get("units") or {}),
            meta=dict(env.get("meta") or {}),
        )

    def simulate(
        self,
        tspan: tuple[float, float] = (0.0, 1.0),
        steps: int = 100,
        observe: Optional[Iterable[str]] = None,
    ) -> Trajectory:
        """Integrate one window from the current state (chained)."""
        fields = self._window_fields(tspan, steps, observe)
        return self._trajectory(self._request("simulate", **fields))

    def predict(
        self,
        horizon: float,
        steps: int = 100,
        observe: Optional[Iterable[str]] = None,
    ) -> Trajectory:
        """Non-advancing rollout ``0..horizon`` from the current state (MPC)."""
        h = _finite(horizon, "predict horizon")
        if h <= 0:
            raise ValueError(f"predict horizon must be > 0 (got {horizon!r})")
        fields: dict = {"horizon": h, "steps": _steps(steps)}
        if observe is not None:
            fields["observe"] = _observe_paths(observe)
        return self._trajectory(self._request("predict", **fields))

    def set_param(self, path: str, value: float) -> None:
        """Change one declared parameter (hot: no cache rebuild)."""
        self._request("set_param", path=str(path), value=_finite(value, "set_param value"))

    def set_params(self, values: Mapping[str, float] | Iterable[tuple[str, float]]) -> None:
        """Change several parameters in one batched fold."""
        rows = _pairs(values, "set_params")
        self._request("set_params", values=rows)

    def set_state(self, path: str, value: float) -> None:
        """Inject a measured state (affects the next solve/simulate start)."""
        self._request("set_state", path=str(path), value=_finite(value, "set_state value"))

    def set_states(self, values: Mapping[str, float] | Iterable[tuple[str, float]]) -> None:
        """Inject several measured states in one batch."""
        rows = _pairs(values, "set_states")
        self._request("set_states", values=rows)

    def clear_state(self) -> None:
        """Drop state injections and the chained trajectory end."""
        self._request("clear_state")

    def snapshot(self) -> dict:
        """Export the session snapshot (params + chained row + injections)."""
        env = self._request("snapshot")
        snap = env.get("snapshot")
        if not isinstance(snap, dict):
            raise EsmlProtocolError("the `snapshot` op returned no snapshot object", raw=env)
        return snap

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        """Restore a snapshot produced by :meth:`snapshot` (same document only)."""
        if not isinstance(snapshot, Mapping):
            raise TypeError("restore expects a snapshot mapping")
        self._request("restore", snapshot=dict(snapshot))

    def info(self) -> Info:
        env = self._request("info")
        return Info(
            doc_hash=env.get("docHash"),
            unknowns=env.get("unknowns"),
            cold_solves=env.get("coldSolves"),
            warm_solves=env.get("warmSolves"),
            last_iters=env.get("lastIters"),
            closed=env.get("closed"),
            dynamic=env.get("dynamic"),
            pending_states=env.get("pendingStates"),
            sim_calls=env.get("simCalls"),
            last_steps=env.get("lastSteps"),
            raw=env,
            source_hash=env.get("sourceHash"),
            engine_version=env.get("engineVersion"),
        )

    # ── internals ──────────────────────────────────────────────────────────
    def stderr_tail(self, lines: int = 20) -> str:
        """The last ``lines`` lines the engine wrote to stderr (diagnostics)."""
        return "\n".join(self._stderr[-lines:])

    def _window_fields(
        self,
        tspan: tuple[float, float],
        steps: int,
        observe: Optional[Iterable[str]],
    ) -> dict:
        try:
            t0, t1 = tspan
        except (TypeError, ValueError) as exc:
            raise ValueError(f"tspan must be (t0, t1), got {tspan!r}") from exc
        fields: dict = {"tspan": [_finite(t0, "tspan[0]"), _finite(t1, "tspan[1]")],
                        "steps": _steps(steps)}
        if observe is not None:
            fields["observe"] = _observe_paths(observe)
        return fields

    def _trajectory(self, env: dict) -> Trajectory:
        series = {
            row["path"]: list(row.get("values", [])) for row in env.get("series", [])
        }
        return Trajectory(
            t=list(env.get("t", [])),
            series=series,
            steps=int(env.get("steps", 0)),
            points=env.get("points"),
            continued=bool(env.get("continued", False)),
            duration_ms=env.get("durationMs"),
            doc_hash=env.get("docHash"),
            raw=env,
            units=dict(env.get("units") or {}),
            meta=dict(env.get("meta") or {}),
        )

    def _write(self, payload: dict) -> None:
        stdin = self._proc.stdin
        if stdin is None:
            raise EsmlClosed("the ESML engine has no stdin pipe")
        try:
            stdin.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._kill()
            raise EsmlClosed(
                f"the ESML engine is not accepting input ({exc}); "
                f"stderr tail:\n{self.stderr_tail()}"
            ) from None

    def _request(self, op: str, **fields: Any) -> dict:
        with self._lock:
            if self._closed:
                raise EsmlClosed(f"session is closed (op `{op}` not sent)")
            payload = {"op": op}
            payload.update(fields)
            self._write(payload)
            env = self._read_envelope()
            if env.get("op") == "error":
                raise EsmlError(
                    str(env.get("error")),
                    op=op,
                    request=env.get("request"),
                    raw=env,
                    code=env.get("code"),
                    hint=env.get("hint"),
                    doc_hash=self.source_hash,
                )
            return env

    def _read_envelope(self) -> dict:
        line = self._next_line()
        try:
            env = json.loads(line)
        except json.JSONDecodeError as exc:
            raise self._protocol_error(
                f"the ESML engine emitted non-JSON output: {line!r} ({exc})"
            ) from None
        if not isinstance(env, dict):
            raise self._protocol_error(f"expected a JSON object envelope, got {env!r}")
        if env.get("apiVersion") != _API:
            raise self._protocol_error(
                f"unexpected apiVersion {env.get('apiVersion')!r} (expected {_API}); "
                "the engine binary is too old or not an ESML engine"
            )
        return env

    def _protocol_error(self, message: str) -> EsmlProtocolError:
        # The stream is out of sync: kill the engine so a later request can
        # never read a stale envelope.
        self._kill()
        return EsmlProtocolError(message)

    def _next_line(self) -> str:
        blank = 0
        while True:
            try:
                if self.timeout is None:
                    item = self._queue.get()
                else:
                    item = self._queue.get(timeout=self.timeout)
            except queue.Empty:
                self._kill()
                raise EsmlTimeout(
                    f"no response from the ESML engine within {self.timeout}s; "
                    f"stderr tail:\n{self.stderr_tail()}"
                ) from None
            if item is None:
                code = self._proc.poll()
                self._closed = True
                raise EsmlClosed(
                    f"the ESML engine exited (code {code}); stderr tail:\n{self.stderr_tail()}"
                )
            line = item.strip()
            if line:
                return line
            blank += 1
            if blank > 100:
                raise EsmlProtocolError("the ESML engine emitted more than 100 blank lines")

    def _kill(self) -> None:
        self._closed = True
        proc = getattr(self, "_proc", None)
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            pass

    def _read_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            self._queue.put(None)
            return
        for line in stdout:
            self._queue.put(line)
        self._queue.put(None)

    def _read_stderr(self) -> None:
        stderr = self._proc.stderr
        if stderr is None:
            return
        for line in stderr:
            self._stderr.append(line.rstrip())
            if len(self._stderr) > 200:
                del self._stderr[:100]


def _finite(value: Any, what: str) -> float:
    """Convert to float and reject NaN/inf before they can reach the engine."""
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} must be a number (got {value!r})") from exc
    if not math.isfinite(out):
        raise ValueError(f"{what} must be finite (got {value!r})")
    return out


def _steps(value: Any) -> int:
    """Validate a step count: an integer >= 1 (booleans are not counts)."""
    if isinstance(value, bool):
        raise ValueError(f"steps must be an integer >= 1 (got {value!r})")
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"steps must be an integer >= 1 (got {value!r})") from None
    if out != value or out < 1:
        raise ValueError(f"steps must be an integer >= 1 (got {value!r})")
    return out


def _pairs(
    values: Mapping[str, float] | Iterable[tuple[str, float]], what: str
) -> list:
    pairs = values.items() if isinstance(values, Mapping) else values
    rows = [{"path": str(p), "value": _finite(v, f"{what} value for {p!r}")} for p, v in pairs]
    if not rows:
        raise ValueError(f"{what} needs at least one (path, value) pair")
    return rows


def _observe_paths(observe: Iterable[str]) -> list:
    paths = [str(p) for p in observe]
    if not paths:
        raise ValueError("observe must name at least one path (omit it to get all variables)")
    return paths
