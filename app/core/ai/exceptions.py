"""Exceptions raised by the AI provider/workflow/orchestration layer.

Extends the Milestone 3 :class:`~app.core.services.exceptions.ServiceError`
hierarchy rather than starting a new one, so a caller that already
catches ``ServiceError`` (the CLI's ``main()``, tests, and later the
GUI) needs no new handling to cover this layer too.
"""

from __future__ import annotations

from app.core.services.exceptions import ServiceError


class ProviderNotConfiguredError(ServiceError):
    """A provider's ``generate()`` was invoked without being configured/available.

    Every real provider added after Milestone 3.5 starts out
    unconfigured (no API key, no network code) until it is actually
    wired up — this is the error that lets the orchestrator/CLI/GUI
    show "not available" instead of a stack trace.
    """


class ProviderRequestError(ServiceError):
    """A real provider call failed (network error, API error response, ...).

    Unused until a real (non-mock) provider exists — kept here now so
    the exception hierarchy a future provider needs already exists.
    """


class WorkflowError(ServiceError):
    """A workflow step failed for a reason not covered by a more specific error."""
