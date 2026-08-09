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

    Base class for every specific real-call failure below. Catch this
    directly for "some real provider call failed, I don't care exactly
    why"; catch a subclass for anything that needs to react differently
    (e.g. the GUI showing a distinct message per category without ever
    parsing a provider-specific error string).
    """


class ProviderAuthenticationError(ProviderRequestError):
    """The provider rejected the request due to an invalid/missing credential."""


class ProviderRateLimitError(ProviderRequestError):
    """The provider rejected the request due to rate limiting or quota exhaustion."""


class ProviderTimeoutError(ProviderRequestError):
    """The provider call did not complete within the configured timeout."""


class ProviderRejectionError(ProviderRequestError):
    """The provider declined to generate content (safety/policy rejection).

    Distinct from :class:`ProviderMalformedResponseError`: this means
    the provider understood the request and explicitly refused it, not
    that its response was unreadable.
    """


class ProviderMalformedResponseError(ProviderRequestError):
    """The provider returned a response this app could not interpret."""


class ProviderNetworkError(ProviderRequestError):
    """A network-level failure occurred before/while reaching the provider."""


class WorkflowError(ServiceError):
    """A workflow step failed for a reason not covered by a more specific error."""
