"""One-shot engine calls — the public surface of the academic edition.

`Session` (resident DTIL: start/predict/snapshot) is a **commercial-edition**
capability. The academic binary exposes the engine core only. These wrappers
run `esml solve` / `esml simulate` as one process per call and parse the
`esml.solve/v1` / `esml.simulate/v1` JSON envelopes; no state is carried
between calls.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .binary import find_binary
from .errors import EsmlError, EsmlProtocolError, EsmlTimeout


@dataclass
class SolveOutput:
    """Steady-state solve from `esml solve --json`."""

    values: dict
    unknowns: Optional[int]
    system: Optional[str]
    raw: dict
    units: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class SimulateOutput:
    """One-shot time integration from `esml simulate --json`."""

    t: list
    series: dict
    steps: int
    system: Optional[str]
    raw: dict
    units: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


def solve(
    path: str | os.PathLike,
    *,
    system: Optional[str] = None,
    libraries: Sequence[str | os.PathLike] = (),
    binary: Optional[str | os.PathLike] = None,
    timeout: Optional[float] = 120.0,
) -> SolveOutput:
    """Solve one document's steady state (no resident session)."""
    args = _base_args("solve", path, system, libraries, binary)
    args.append("--json")
    env = _run(args, "esml.solve/v1", timeout, "solve")
    rows = env.get("values", [])
    values = {str(row["path"]): float(row["value"]) for row in rows}
    units = {
        str(row["path"]): str(row["unit"])
        for row in rows
        if row.get("unit") is not None
    }
    return SolveOutput(
        values,
        env.get("unknowns"),
        env.get("system"),
        env,
        units=units,
        meta=dict(env.get("meta") or {}),
    )


def simulate(
    path: str | os.PathLike,
    tspan: tuple[float, float] = (0.0, 1.0),
    steps: int = 100,
    observe: Optional[Iterable[str]] = None,
    *,
    system: Optional[str] = None,
    libraries: Sequence[str | os.PathLike] = (),
    binary: Optional[str | os.PathLike] = None,
    timeout: Optional[float] = 120.0,
) -> SimulateOutput:
    """Integrate one document once over ``tspan`` (no resident session)."""
    t0, t1 = _tspan(tspan)
    n = _steps(steps)
    args = _base_args("simulate", path, system, libraries, binary)
    args += ["--tspan", f"{t0},{t1}", "--steps", str(n), "--json"]
    if observe is not None:
        paths = [str(p) for p in observe]
        if not paths:
            raise ValueError("observe must name at least one path (omit it for all variables)")
        args += ["--observe", ",".join(paths)]
    env = _run(args, "esml.simulate/v1", timeout, "simulate")
    columns = [str(c) for c in env.get("columns", [])]
    rows = env.get("rows", [])
    series = {
        col: [float(row[i]) for row in rows] for i, col in enumerate(columns)
    }
    units = {str(k): str(v) for k, v in (env.get("units") or {}).items()}
    return SimulateOutput(
        list(env.get("t", [])),
        series,
        int(env.get("steps", 0)),
        env.get("system"),
        env,
        units=units,
        meta=dict(env.get("meta") or {}),
    )


def _base_args(op, path, system, libraries, binary) -> list:
    args = [find_binary(binary), op, os.fspath(path)]
    if system:
        args += ["--system", str(system)]
    for lib in libraries:
        args += ["-L", os.fspath(lib)]
    return args


def _run(args: list, api: str, timeout: Optional[float], op: str) -> dict:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise EsmlError(f"the ESML engine binary disappeared: {args[0]!r}", op=op) from None
    except subprocess.TimeoutExpired:
        raise EsmlTimeout(f"`esml {op}` did not finish within {timeout}s", op=op) from None
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip()
        if not message:
            message = f"`esml {op}` exited with code {proc.returncode}"
        raise EsmlError(message, op=op, raw={"returncode": proc.returncode})
    try:
        env = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise EsmlProtocolError(
            f"`esml {op} --json` emitted non-JSON output: {proc.stdout!r} ({exc})", op=op
        ) from None
    if not isinstance(env, dict) or env.get("apiVersion") != api:
        raise EsmlProtocolError(
            f"unexpected envelope from `esml {op} --json` (expected {api}): {env!r}", op=op
        )
    return env


def _tspan(tspan) -> tuple[float, float]:
    try:
        t0, t1 = tspan
    except (TypeError, ValueError) as exc:
        raise ValueError(f"tspan must be (t0, t1), got {tspan!r}") from exc
    return _finite(t0, "tspan[0]"), _finite(t1, "tspan[1]")


def _finite(value: Any, what: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{what} must be a number (got {value!r})") from exc
    if not math.isfinite(out):
        raise ValueError(f"{what} must be finite (got {value!r})")
    return out


def _steps(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"steps must be an integer >= 1 (got {value!r})")
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"steps must be an integer >= 1 (got {value!r})") from None
    if out != value or out < 1:
        raise ValueError(f"steps must be an integer >= 1 (got {value!r})")
    return out
