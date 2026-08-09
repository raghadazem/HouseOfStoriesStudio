"""Domain-specific exceptions raised by the service layer.

All inherit :class:`ServiceError` so callers (CLI, tests, and later the
GUI) can catch one base class when they just need "something in the
service layer went wrong," while still being able to catch a specific
subtype when they need to react differently (e.g. show a "not found"
message vs. a validation error).

None of these are ever swallowed inside a service — every raise site
either propagates immediately or is caught only to add context/perform
cleanup before re-raising (see ``AssetImportError`` usage in
``asset_import_service.py``).
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for all service-layer errors."""


class NotFoundError(ServiceError):
    """The requested entity does not exist."""


class ValidationError(ServiceError):
    """Input failed domain validation."""


class ConflictError(ServiceError):
    """The operation conflicts with existing state (e.g. a duplicate)."""


class InvalidTransitionError(ServiceError):
    """An invalid state transition was attempted.

    E.g. an episode status change that skips required steps, or
    approving a character version that isn't in review.
    """


class PrivacyViolationError(ValidationError):
    """The operation would violate the personal-reference-photo privacy rule."""


class ChecklistError(ServiceError):
    """A readiness checklist blocked an operation that requires it to pass."""


class CharacterLockIncompleteError(ServiceError):
    """A CharacterVersion is missing required Character Lock fields.

    Raised instead of a generic validation error so the caller (the
    GUI, per the founder's explicit requirement) can read
    ``missing_fields`` and explain exactly what is missing, rather than
    showing an unhelpful generic message.
    """

    def __init__(self, message: str, missing_fields: list[str]) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields


class ExportBlockedError(ServiceError):
    """A final export was requested but blocking checklist issues exist."""


class TemplateRenderError(ServiceError):
    """Prompt template rendering failed (missing variables, unsafe syntax, ...)."""


class AssetImportError(ServiceError):
    """An asset import failed after validation.

    Raised only once both the database and filesystem have already been
    rolled back to their pre-import state — see
    ``AssetImportService.import_asset``. Carries the original exception
    via ``__cause__`` (standard ``raise ... from err`` chaining).
    """
