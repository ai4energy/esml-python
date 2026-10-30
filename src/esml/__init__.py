"""ESML: MIT Python client for the ESML engine.

The engine (``esml``) is a commercial binary distributed separately; this
package only runs its public command line / JSON protocol. The public surface
is one-shot: :func:`solve` and :func:`simulate` start one engine process per
call and keep no state. :class:`Session` (resident DTIL sessions) requires the
commercial engine edition.

Quick start::

    from esml import simulate, solve

    steady = solve("plant.esml", system="Plant")
    print(steady.values)

    traj = simulate("plant.esml", (0.0, 60.0), 60, observe=["tank.T"])
    print(traj.series["tank.T"][-1])
"""

from __future__ import annotations

from .binary import engine_version, find_binary
from .errors import (
    EsmlBinaryNotFound,
    EsmlClosed,
    EsmlError,
    EsmlProtocolError,
    EsmlTimeout,
)
from .oneshot import SimulateOutput, SolveOutput, simulate, solve
from .session import Info, Session, SolveResult, Trajectory

__version__ = "0.1.0"

__all__ = [
    "Session",
    "SolveResult",
    "Trajectory",
    "Info",
    "solve",
    "simulate",
    "SolveOutput",
    "SimulateOutput",
    "EsmlError",
    "EsmlBinaryNotFound",
    "EsmlProtocolError",
    "EsmlTimeout",
    "EsmlClosed",
    "find_binary",
    "engine_version",
    "__version__",
]
