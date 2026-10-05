from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_cancel_check: ContextVar[Callable[[], bool] | None] = ContextVar(
    "job_cancel_check",
    default=None,
)
_pause_check: ContextVar[Callable[[], bool] | None] = ContextVar(
    "job_pause_check",
    default=None,
)
_job_id: ContextVar[int | None] = ContextVar("job_id", default=None)
_job_run_id: ContextVar[str | None] = ContextVar("job_run_id", default=None)


class JobDeferredError(RuntimeError):
    """Signal that a healthy asynchronous job must be polled again later."""

    def __init__(self, message: str, *, delay_seconds: int = 30) -> None:
        super().__init__(message)
        if delay_seconds <= 0:
            raise ValueError("delay_seconds must be positive")
        self.delay_seconds = delay_seconds


def job_cancellation_requested() -> bool:
    check = _cancel_check.get()
    pause_check = _pause_check.get()
    return bool((check and check()) or (pause_check and pause_check()))


def job_pause_requested() -> bool:
    check = _pause_check.get()
    return bool(check and check())


def current_job_id() -> int | None:
    return _job_id.get()


def current_job_run_id() -> str | None:
    return _job_run_id.get()


@contextmanager
def activate_job_cancellation(check: Callable[[], bool]) -> Iterator[None]:
    token: Token[Callable[[], bool] | None] = _cancel_check.set(check)
    try:
        yield
    finally:
        _cancel_check.reset(token)


@contextmanager
def activate_job_pause(check: Callable[[], bool]) -> Iterator[None]:
    token: Token[Callable[[], bool] | None] = _pause_check.set(check)
    try:
        yield
    finally:
        _pause_check.reset(token)


@contextmanager
def activate_job_execution(job_id: int, run_id: str | None) -> Iterator[None]:
    job_token: Token[int | None] = _job_id.set(job_id)
    run_token: Token[str | None] = _job_run_id.set(run_id)
    try:
        yield
    finally:
        _job_run_id.reset(run_token)
        _job_id.reset(job_token)
