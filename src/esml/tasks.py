"""Typed access to the engine's compute-task runner (``esml tasks``).

A `<computeTasks>` document declares a set of tasks against a system; the
engine runs them and reports one result per task.  The commercial engine
speaks a JSON envelope for this command — ``esml.tasks/v1`` — and this
module is the client's typed view of it.

The envelope looks like::

    {
      "apiVersion": "esml.tasks/v1",
      "ok": true,
      "system": "S",
      "tasks": [
        {"name": "sim1", "kind": "simulate", "target": "S",
         "units": {}, "meta": {...}, "outcome": {...}}
      ]
    }

``ok: false`` carries an ``error`` object (``code`` / ``message``) and is
raised as :class:`EsmlError` with the whole envelope in ``raw``.

Example
-------
>>> from esml import tasks
>>> out = tasks("batch.esml", system="S")
>>> for task in out.tasks:
...     print(task.name, task.kind, task.outcome)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from .cli import run_cli
from .errors import EsmlError, EsmlProtocolError

#: The envelope version this client speaks.
API_VERSION = "esml.tasks/v1"


@dataclass
class TaskResult:
    """One task's result.

    Attributes
    ----------
    name:
        The task's name (as declared in the document).
    kind:
        The task kind (``simulate``, ``forecast``, ``optimize``, …).
    target:
        The system the task ran against.
    units:
        Path → SI dimension expressions for the task's outputs.
    meta:
        Engine metadata (engine version, document hash, timings, …).
    outcome:
        The task's outcome, as the engine reported it.
    raw:
        The task object of the envelope, verbatim.
    """

    name: str
    kind: str
    target: Optional[str]
    units: dict
    meta: dict
    outcome: Any
    raw: dict = field(default_factory=dict)


@dataclass
class TasksOutput:
    """The result of one ``esml tasks`` run."""

    tasks: list
    raw: dict

    def __len__(self) -> int:
        return len(self.tasks)

    def __iter__(self):
        return iter(self.tasks)

    def by_name(self, name: str) -> Optional[TaskResult]:
        """The task called ``name``, or ``None``."""
        for task in self.tasks:
            if task.name == name:
                return task
        return None


def tasks(
    path: str | os.PathLike,
    *,
    system: Optional[str] = None,
    libraries: Sequence[str | os.PathLike] = (),
    jobs: Optional[int] = None,
    binary: Optional[str | os.PathLike] = None,
    timeout: float = 300.0,
) -> TasksOutput:
    """Run a `<computeTasks>` document and return its results.

    Parameters
    ----------
    path:
        The compute-task document (an ``<esml>`` wrapper around
        ``<computeTasks>``, or a bare ``<computeTasks>`` plus ``--source``).
    system:
        System override for the task target.
    libraries:
        Extra library roots passed as ``-L``.
    jobs:
        Parallel task slots requested from the engine (``--jobs``).  ``None``
        leaves the engine's own default alone.
    binary:
        Explicit path to the ``esml`` executable (otherwise ``$ESML_BIN`` or
        ``PATH``).
    timeout:
        Wall-clock limit in seconds; on expiry :class:`EsmlTimeout` is
        raised.

    Raises
    ------
    EsmlError
        The engine failed (non-zero exit) or answered ``ok: false``.
    EsmlProtocolError
        The engine's answer was not an ``esml.tasks/v1`` envelope.
    """
    argv = ["tasks", os.fspath(path), "--json"]
    if system:
        argv += ["--system", str(system)]
    for lib in libraries:
        argv += ["-L", os.fspath(lib)]
    if jobs is not None:
        argv += ["--jobs", str(_jobs(jobs))]
    res = run_cli(argv, binary=binary, timeout=timeout)

    if res.code != 0:
        raise EsmlError(
            _failure_message(res),
            op="tasks",
            code="tasks.failed",
            raw={"code": res.code, "stdout": res.stdout, "stderr": res.stderr},
        )

    try:
        env = json.loads(res.stdout)
    except json.JSONDecodeError as exc:
        raise EsmlProtocolError(
            f"`esml tasks --json` emitted non-JSON output: {res.stdout!r} ({exc})",
            op="tasks",
        ) from None
    if not isinstance(env, dict):
        raise EsmlProtocolError(
            f"`esml tasks --json` did not return a JSON object: {res.stdout!r}", op="tasks"
        )
    if env.get("apiVersion") != API_VERSION:
        raise EsmlProtocolError(
            f"unexpected envelope from `esml tasks --json` (expected {API_VERSION}): "
            f"{env.get('apiVersion')!r}",
            op="tasks",
            raw=env,
        )
    if env.get("ok") is False:
        raise EsmlError(
            _error_message(env),
            op="tasks",
            code=_error_code(env),
            raw=env,
        )

    rows = env.get("tasks")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise EsmlProtocolError(
            f"`esml tasks --json` returned a non-array `tasks` field: {rows!r}", op="tasks"
        )
    return TasksOutput(
        [_task_result(row, env) for row in rows if isinstance(row, dict)],
        env,
    )


# ── internals ────────────────────────────────────────────────────────────


def _failure_message(res) -> str:
    """The engine's own error line, if it wrote one.

    The engine's stderr mixes warnings and the final ``error:`` line; the
    error line is the answer, the rest stays reachable in ``raw``.
    """
    text = (res.stderr or res.stdout or "").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    errors = [line for line in lines if line.startswith("error: ")]
    if errors:
        return errors[-1][len("error: "):]
    if lines:
        return "\n".join(lines)
    return f"`esml tasks` exited with code {res.code}"


def _task_result(row: dict, env: dict) -> TaskResult:
    return TaskResult(
        name=str(row.get("name", "")),
        kind=str(row.get("kind", "")),
        target=row.get("target") or env.get("system"),
        units=dict(row.get("units") or {}),
        meta=dict(row.get("meta") or {}),
        outcome=row.get("outcome"),
        raw=row,
    )


def _error_message(env: dict) -> str:
    error = env.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "the task run failed")
    if isinstance(error, str) and error:
        return error
    return "the task run failed"


def _error_code(env: dict) -> Optional[str]:
    error = env.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return str(code) if code is not None else None
    return None


def _jobs(value: Any) -> int:
    """Validate the job count before it reaches the engine."""
    if isinstance(value, bool):
        raise ValueError(f"jobs must be an integer >= 1 (got {value!r})")
    try:
        out = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"jobs must be an integer >= 1 (got {value!r})") from None
    if out != value or out < 1:
        raise ValueError(f"jobs must be an integer >= 1 (got {value!r})")
    return out
