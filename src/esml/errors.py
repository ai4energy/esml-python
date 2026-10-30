"""Exceptions raised by the ESML Python client.

The client is a thin JSON-over-stdio wrapper around the `esml` engine binary.
Engine-side failures arrive as `{"op":"error","error":…}` envelopes; those are
raised as :class:`EsmlError` with the op, the engine message and the raw
envelope so callers never have to parse strings.
"""

from __future__ import annotations


class EsmlError(Exception):
    """An error reported by the ESML engine (or by the client before sending)."""

    def __init__(self, message: str, *, op: str | None = None,
                 request: str | None = None, raw: dict | None = None,
                 code: str | None = None, hint: str | None = None,
                 doc_hash: str | None = None) -> None:
        super().__init__(message)
        self.op = op
        self.request = request
        self.raw = raw
        #: Stable machine code from `esml.error/v1` (``None`` for client errors).
        self.code = code
        #: Actionable suggestion supplied by the engine, if any.
        self.hint = hint
        #: SHA-256 of the source document (one-shot errors), if available.
        self.doc_hash = doc_hash


class EsmlBinaryNotFound(EsmlError):
    """The `esml` engine binary could not be located."""


class EsmlProtocolError(EsmlError):
    """The engine emitted something that is not an `esml.session/v1` envelope."""


class EsmlTimeout(EsmlError):
    """The engine did not answer an op within the session timeout."""


class EsmlClosed(EsmlError):
    """The session (or the engine process) is closed."""
