"""Exit codes and the error type. Standard library only, so light helpers can import it."""

from __future__ import annotations

# Stable contract for agents and shell pipelines.
EXIT_OK = 0
EXIT_ERROR = 1  # unexpected failure
EXIT_USAGE = 2  # bad arguments / schema validation failed
# 3 is retired (it was the cost guard until 1.2) and stays unused, so the other codes keep their meaning.
EXIT_AUTH = 4  # no key / key rejected
EXIT_API = 5  # fal returned an error for the request
EXIT_TIMEOUT = 6  # still running at --timeout; resumable with `fetch`


class FalkitError(Exception):
    """An error with a user-facing message, an exit code, and an optional hint."""

    def __init__(self, message: str, code: int = EXIT_ERROR, hint: str | None = None):
        super().__init__(message)
        self.code = code
        self.hint = hint
