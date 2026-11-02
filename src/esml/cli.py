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

import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Sequence

from .binary import find_binary
from .errors import EsmlError, EsmlProtocolError, EsmlTimeout

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


def check(
    path: str | os.PathLike,
    *,
    libraries: Sequence[str | os.PathLike] = (),
    binary: Optional[str | os.PathLike] = None,
    timeout: float = 120.0,
) -> list[dict]:
    """Front-validate a document (or a directory of documents).

    Runs ``esml check --json`` and returns the engine's report array — one
    entry per validated file, each with ``file`` / ``well_formed`` /
    ``summary`` / ``findings``.

    The call fails — :class:`EsmlError`, with the engine's stderr in the
    message and the parsed report in ``raw["reports"]`` — when the engine
    exits non-zero **or** reports an ``error``-severity finding.  Both
    signals are needed: the engine's ``--json`` path does not always carry
    the verdict in the exit code (``check-units --json`` exits 0 even when
    it found errors), so trusting the exit code alone would let a broken
    document pass as "checked".  Warnings alone do not fail the call.
    """
    return _check_json(
        "check", path, libraries=libraries, binary=binary, timeout=timeout
    )


def check_units(
    path: str | os.PathLike,
    *,
    libraries: Sequence[str | os.PathLike] = (),
    binary: Optional[str | os.PathLike] = None,
    timeout: float = 120.0,
) -> list[dict]:
    """Check the unit declarations of a document (or a directory).

    Runs ``esml check-units --json`` and returns the engine's report array
    (same shape as :func:`check`, with the unit-specific summary).  The
    failure rule is the same as :func:`check`.
    """
    return _check_json(
        "check-units", path, libraries=libraries, binary=binary, timeout=timeout
    )


# ── internals ────────────────────────────────────────────────────────────


def _check_json(
    op: str,
    path: str | os.PathLike,
    *,
    libraries: Sequence[str | os.PathLike],
    binary: Optional[str | os.PathLike],
    timeout: float,
) -> list[dict]:
    argv = [op, os.fspath(path), "--json"]
    for lib in libraries:
        argv += ["-L", os.fspath(lib)]
    res = run_cli(argv, binary=binary, timeout=timeout)
    payload = _maybe_json(res.stdout)
    reports = payload if isinstance(payload, list) else None
    errors = _error_findings(reports)
    if res.code != 0 or errors:
        # The engine prints its report *and* fails — keep the report
        # reachable through the exception.
        raise EsmlError(
            _check_message(op, res, errors),
            op=op,
            code=f"{op}.failed",
            raw={
                "code": res.code,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "reports": reports,
            },
        )
    if not isinstance(payload, list):
        raise EsmlProtocolError(
            f"`esml {op} --json` did not return a JSON array: {res.stdout!r}", op=op
        )
    return [row for row in payload if isinstance(row, dict)]


def _error_findings(reports) -> list:
    """Every ``error``-severity finding in a report array."""
    found = []
    if not isinstance(reports, list):
        return found
    for report in reports:
        if not isinstance(report, dict):
            continue
        for finding in report.get("findings") or []:
            if isinstance(finding, dict) and finding.get("severity") == "error":
                found.append(finding)
    return found


def _check_message(op: str, res: CLIResult, errors: list) -> str:
    """A message that says *what* the validator objected to."""
    stderr = (res.stderr or "").strip()
    if stderr.startswith("error: "):
        stderr = stderr[len("error: "):]
    if stderr:
        return stderr
    if errors:
        head = "; ".join(f"{f.get('code')}: {f.get('message')}" for f in errors[:3])
        more = "" if len(errors) <= 3 else f" (and {len(errors) - 3} more)"
        return f"`esml {op}` reported {len(errors)} error finding(s): {head}{more}"
    return f"`esml {op}` exited with code {res.code}"


def _maybe_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
