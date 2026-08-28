"""Run CPU-bound or untrusted mathematical work in a killable child process."""

from __future__ import annotations

import multiprocessing as mp
from collections.abc import Callable, Mapping
from typing import Any


class ToolTimeoutError(TimeoutError):
    """Raised when a child calculation exceeds its wall-clock budget."""


class ToolProcessError(RuntimeError):
    """Raised when a child calculation crashes or cannot return a result."""


def _worker(send_connection, function: Callable[..., Any], kwargs: dict[str, Any]) -> None:
    try:
        result = function(**kwargs)
        send_connection.send(("ok", result))
    except BaseException as exc:  # child must convert every failure into data
        send_connection.send(("error", type(exc).__name__, str(exc)[:1000]))
    finally:
        send_connection.close()


def run_with_timeout(
    function: Callable[..., Any],
    kwargs: Mapping[str, Any],
    timeout_seconds: float,
) -> Any:
    """Execute ``function(**kwargs)`` in a spawned process with a hard timeout."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    context = mp.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker,
        args=(send_connection, function, dict(kwargs)),
        daemon=True,
    )
    try:
        process.start()
        send_connection.close()
        process.join(timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join(1.0)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(1.0)
            raise ToolTimeoutError(f"calculation exceeded {timeout_seconds:g} seconds")
        if not receive_connection.poll():
            raise ToolProcessError(
                f"calculation process exited without a result (exitcode={process.exitcode})"
            )
        message = receive_connection.recv()
        if message[0] == "ok":
            return message[1]
        _, error_type, error_message = message
        raise ToolProcessError(f"{error_type}: {error_message}")
    except (ToolTimeoutError, ToolProcessError):
        raise
    except Exception as exc:
        raise ToolProcessError(f"unable to start calculation process: {exc}") from exc
    finally:
        receive_connection.close()
        if process.is_alive():
            process.terminate()
            process.join(1.0)

