"""Stable router error and request-size contracts shared by HTTP adapters."""

from __future__ import annotations


MAX_REQUEST_BYTES = 16 * 1024 * 1024


class RouterError(Exception):
    """Raised for HTTP-mappable router failures with an explicit status code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
