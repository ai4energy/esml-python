"""Full-surface command line access to the ESML engine.

The client is a thin wrapper around the engine's public command line. This
module holds the *unrestricted* entry point — :func:`run_cli` — plus the
typed wrappers for the front validators, the structural report and the
flattened dump.

Two rules shape the design:

* **The client does not restrict the subcommand.**  ``esml session``,
  ``esml encrypt`` and every other subcommand may be called through
  :func:`run_cli`; whether the *installed edition* supports them is the
  engine's decision, not the client's.  A white list here would silently
  shrink the client's reach on the very editions that need it most.
* **The academic edition's only limit is the unknown count.**  The engine
  refuses models with more than :data:`MAX_UNKNOWNS` unknowns; the client
  surfaces that refusal instead of hiding it.

Example
-------
>>> from esml import run_cli
>>> res = run_cli(["check", "plant.esml", "--json"])
>>> res.code
0
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .binary import find_binary
from .errors import EsmlError, EsmlTimeout

#: The academic edition's hard limit: the engine refuses to flatten a model
#: with more unknowns than this.  The commercial edition has no such limit.
MAX_UNKNOWNS = 16_384

#: Message used whenever the client has to refuse an oversized model.
ACADEMIC_LIMIT_MESSAGE = (
    "学术版上限 16384，商业版请用商业二进制/客户端"
)


@dataclass
class CLIResult:
    """The raw result of one engine invocation.

    Attributes
    ----------
    stdout:
        Everything the engine wrote to stdout (decoded as text).
    stderr:
        Everything the engine wrote to stderr.
    code:
        The process exit code.
    args:
        The argument vector that was executed (binary first).
    """

    stdout: str
    stderr: str
    code: int
    args: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        """``True`` when the engine exited with code 0."""
        return self.code == 0


def run_cli(
    args: Sequence[str],
    *,
    input: Optional[str] = None,  # noqa: A002 — the public API name
    timeout: float = 120.0,
    binary: Optional[str | os.PathLike] = None,
) -> CLIResult:
    """Run any engine subcommand and return its raw result.

    Parameters
    ----------
    args:
        The engine arguments *after* the binary — the subcommand first
        (``["check", "plant.esml", "--json"]``).  Any subcommand is allowed:
        commercial-only commands (``session``, ``encrypt``, …) may be called
        too, and the engine itself decides whether the installed edition
        supports them.
    input:
        Optional text written to the engine's stdin before it is closed.
    timeout:
        Wall-clock limit in seconds; on expiry the engine is killed and
        :class:`EsmlTimeout` is raised.
    binary:
        Explicit path to the ``esml`` executable (otherwise ``$ESML_BIN`` or
        ``PATH``).

    Returns
    -------
    CLIResult
        stdout / stderr / exit code.  A **non-zero exit is not an exception**
        here — only a timeout is; the typed wrappers decide which exit
        codes are failures.
    """
    exe = find_binary(binary)
    argv = [exe, *[str(a) for a in args]]
    try:
        proc = subprocess.run(
            argv,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise EsmlError(
            f"the ESML engine binary disappeared: {exe!r}", op=args[0] if args else None
        ) from None
    except subprocess.TimeoutExpired:
        raise EsmlTimeout(
            f"`{argv[1] if len(argv) > 1 else argv[0]}` did not finish within {timeout}s",
            op=args[0] if args else None,
        ) from None
    return CLIResult(
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        code=proc.returncode,
        args=tuple(argv),
    )
