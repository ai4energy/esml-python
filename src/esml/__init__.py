"""ESML: MIT Python client for the ESML engine.

The engine (``esml``) is a commercial binary distributed separately; this
package only runs its public command line / JSON protocol.

The public surface is the **whole command line**:

* :func:`solve` / :func:`simulate` — one-shot solving (one engine process
  per call, no state kept between calls);
* :func:`check` / :func:`check_units` — the front validators;
* :func:`tasks` — the compute-task runner;
* :func:`inspect` / :func:`dump` — the structural report and the flattened
  listing;
* :func:`run_cli` — an unrestricted escape hatch for any subcommand.

The client does **not** restrict which subcommand may be called: whether the
installed edition supports it is the engine's decision.  The academic
edition's only limit is the unknown count (:data:`MAX_UNKNOWNS`).

:class:`Session` (resident DTIL sessions) requires the commercial engine
edition.

Quick start::

    from esml import check, simulate, solve

    reports = check("plant.esml")
    print(reports[0]["summary"])

    steady = solve("plant.esml", system="Plant")
    print(steady.values)

    traj = simulate("plant.esml", (0.0, 60.0), 60, observe=["tank.T"])
    print(traj.series["tank.T"][-1])
"""

from __future__ import annotations

from .binary import engine_version, find_binary
from .cli import (
    MAX_UNKNOWNS,
    CLIResult,
    check,
    check_units,
    dump,
    inspect,
    run_cli,
    version,
)
from .errors import (
    EsmlBinaryNotFound,
    EsmlClosed,
    EsmlError,
    EsmlProtocolError,
    EsmlTimeout,
)
from .oneshot import SimulateOutput, SolveOutput, simulate, solve
from .session import Info, Session, SolveResult, Trajectory
from .tasks import TaskResult, TasksOutput, tasks

__version__ = "0.4.0"

__all__ = [
    "Session",
    "SolveResult",
    "Trajectory",
    "Info",
    "solve",
    "simulate",
    "SolveOutput",
    "SimulateOutput",
    "CLIResult",
    "MAX_UNKNOWNS",
    "run_cli",
    "check",
    "check_units",
    "inspect",
    "dump",
    "version",
    "tasks",
    "TaskResult",
    "TasksOutput",
    "EsmlError",
    "EsmlBinaryNotFound",
    "EsmlProtocolError",
    "EsmlTimeout",
    "EsmlClosed",
    "find_binary",
    "engine_version",
    "__version__",
]
