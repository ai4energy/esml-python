"""Locate the ESML **engine binary** and read its version.

Only the engine binary is required. This package intentionally does not need
(or ship) the worker, the MCP server, or any platform component: the entire
client/server contract is the `esml session` JSON protocol
(`esml.session/v1`).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from .errors import EsmlBinaryNotFound

#: `esml --version` prints e.g. `ESML v1.8.0 · Energy System Modeling Language …`
_VERSION_RE = re.compile(r"\bv(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b")


def find_binary(explicit: str | os.PathLike | None = None) -> str:
    """Return the path to the `esml` executable.

    Resolution order: ``explicit`` argument → ``$ESML_BIN`` → ``PATH``.
    A path that was given explicitly (or via ``ESML_BIN``) but is not an
    executable file is a **loud** error — the client never silently falls
    back to another binary.
    """
    for source, candidate in (("argument", explicit), ("ESML_BIN", os.environ.get("ESML_BIN"))):
        if not candidate:
            continue
        path = os.path.expanduser(os.fspath(candidate))
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        raise EsmlBinaryNotFound(
            f"the ESML engine binary from {source} is not an executable file: {path!r}"
        )
    found = shutil.which("esml")
    if found:
        return found
    raise EsmlBinaryNotFound(
        "the ESML engine binary (`esml`) was not found: put it on PATH or set "
        "ESML_BIN=<path>. Only the engine binary is required — no worker, MCP "
        "server, or platform component is needed."
    )


def engine_version(binary: str, timeout: float = 10.0) -> str | None:
    """Return the engine version string (e.g. ``1.8.0``), or ``None``.

    The version is informational; protocol compatibility is checked by the
    ``apiVersion`` of the first envelope, not by this string.
    """
    try:
        out = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    match = _VERSION_RE.search(out.stdout or out.stderr)
    return match.group(1) if match else None
