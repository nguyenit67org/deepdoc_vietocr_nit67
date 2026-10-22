"""Request-local cooperative cancellation, inert for ordinary pipeline callers."""
from contextlib import contextmanager
from contextvars import ContextVar

_event = ContextVar("ocr_cancel_event", default=None)


class ProcessingCancelled(Exception):
    pass


def check_cancelled():
    event = _event.get()
    if event is not None and event.is_set():
        raise ProcessingCancelled("PDF processing cancelled")


@contextmanager
def cancellation_scope(event):
    token = _event.set(event)
    try:
        check_cancelled()
        yield
    finally:
        _event.reset(token)
