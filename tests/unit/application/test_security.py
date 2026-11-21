import pytest

from core.application.security import Action, AuthorizationPolicy, Principal, Role
from core.domain.errors import AuthorizationDenied


def test_role_policy_enforces_operator_reviewer_and_admin_actions():
    policy = AuthorizationPolicy()
    operator = Principal("operator-1", frozenset({Role.OPERATOR}))
    reviewer = Principal("reviewer-1", frozenset({Role.REVIEWER}))
    admin = Principal("admin-1", frozenset({Role.ADMIN}))

    policy.require(operator, Action.SUBMIT_JOB)
    policy.require(reviewer, Action.APPROVE_JOB)
    policy.require(admin, Action.MANAGE_CHANNEL)

    with pytest.raises(AuthorizationDenied):
        policy.require(operator, Action.APPROVE_JOB)
    with pytest.raises(AuthorizationDenied):
        policy.require(reviewer, Action.MANAGE_CHANNEL)


def test_unknown_or_empty_identity_is_denied_by_default():
    with pytest.raises(AuthorizationDenied):
        AuthorizationPolicy().require(
            Principal("", frozenset({Role.ADMIN})), Action.MANAGE_CHANNEL
        )
