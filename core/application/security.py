"""Default-deny authorization values shared by application facades."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from core.domain.errors import AuthorizationDenied


class Role(str, Enum):
    OPERATOR = "OPERATOR"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


class Action(str, Enum):
    SUBMIT_JOB = "SUBMIT_JOB"
    READ_JOB = "READ_JOB"
    CANCEL_JOB = "CANCEL_JOB"
    REVIEW_JOB = "REVIEW_JOB"
    APPROVE_JOB = "APPROVE_JOB"
    RECOVER_PUBLISH = "RECOVER_PUBLISH"
    MANAGE_CHANNEL = "MANAGE_CHANNEL"
    READ_AUDIT = "READ_AUDIT"


@dataclass(frozen=True, slots=True)
class Principal:
    principal_id: str
    roles: frozenset[Role]


class AuthorizationPolicy:
    _GRANTS: ClassVar[dict[Role, set[Action]]] = {
        Role.OPERATOR: {Action.SUBMIT_JOB, Action.READ_JOB, Action.CANCEL_JOB},
        Role.REVIEWER: {
            Action.READ_JOB,
            Action.REVIEW_JOB,
            Action.APPROVE_JOB,
            Action.RECOVER_PUBLISH,
        },
        Role.ADMIN: {Action.MANAGE_CHANNEL, Action.READ_AUDIT, Action.READ_JOB},
    }

    def require(self, principal: Principal, action: Action) -> None:
        if not principal.principal_id.strip() or not any(
            action in self._GRANTS.get(role, set()) for role in principal.roles
        ):
            raise AuthorizationDenied("Action is not permitted")
