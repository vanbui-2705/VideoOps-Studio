"""Typed errors raised by the workflow domain."""

from __future__ import annotations


class WorkflowError(Exception):
    """Base class for expected workflow failures."""


class InvalidTransition(WorkflowError):
    """Raised when a job state transition violates the state machine."""


class DomainValidationError(WorkflowError):
    """Raised when a typed request violates a domain invariant."""


class ChannelNotFound(WorkflowError):
    """Raised when a request references an unknown channel."""


class JobNotFound(WorkflowError):
    """Raised when a workflow job cannot be found."""


class RevisionConflict(WorkflowError):
    """Raised when a caller attempts to mutate a stale job revision."""


class InvalidCommand(WorkflowError):
    """Raised when a command is invalid for a job or payload."""


class ApprovalPreconditionFailed(WorkflowError):
    """Raised when a job cannot cross the human review gate."""


class DuplicateRequest(WorkflowError):
    """Raised when persistence detects a conflicting request identifier."""


class TargetAlreadyCompleted(WorkflowError):
    """Raised when a completed target receives a mutating command."""


class ReconciliationRequired(WorkflowError):
    """Raised when an unknown publish result must be reconciled first."""


class WorkQueueConflict(WorkflowError):
    """Raised when a worker mutates work it does not currently lease."""


class ChannelValidationError(WorkflowError):
    """Raised when a channel profile violates a safe configuration policy."""


class ChannelProfileNotFound(WorkflowError):
    """Raised when a channel profile does not exist."""


class ChannelAlreadyExists(WorkflowError):
    """Raised when a create request reuses a channel identifier."""


class ChannelRevisionConflict(WorkflowError):
    """Raised when a channel update uses a stale revision."""


class ChannelAdministrationDisabled(WorkflowError):
    """Raised when profile mutation is disabled by deployment policy."""


class CredentialUnavailable(WorkflowError):
    """Raised when a referenced provider credential bundle is incomplete."""


class UnsafeWorkspacePath(WorkflowError):
    """Raised when a media path escapes its revision-scoped job workspace."""


class MediaPreparationError(WorkflowError):
    """Base class for sanitized media pipeline failures."""

    code = "MEDIA_PREPARATION"
    retryable = False


class MediaConfigurationError(MediaPreparationError):
    code = "MEDIA_CONFIGURATION"


class MediaTransientError(MediaPreparationError):
    code = "MEDIA_TRANSIENT"
    retryable = True


class MediaTimeoutError(MediaPreparationError):
    code = "MEDIA_TIMEOUT"
    retryable = True


class MediaInvalidOutput(MediaPreparationError):
    code = "MEDIA_INVALID_OUTPUT"
