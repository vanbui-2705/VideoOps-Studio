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
