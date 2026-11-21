import pytest

from core.application.audit_query import AuditQuery, AuditQueryService
from core.application.security import AuthorizationPolicy, Principal, Role
from core.domain.errors import AuthorizationDenied


class Reader:
    def __init__(self):
        self.query = None

    def search(self, query):
        self.query = query
        return ()


def test_only_admin_can_query_bounded_audit_records():
    reader = Reader()
    admin = AuditQueryService(
        reader,
        Principal("admin", frozenset({Role.ADMIN})),
        AuthorizationPolicy(),
    )

    assert (
        admin.search(
            AuditQuery(
                actor_type="USER",
                actor_id="reviewer-7",
                channel_id="tech_vn",
                page_size=25,
            )
        )
        == ()
    )
    assert reader.query.channel_id == "tech_vn"
    assert reader.query.actor_id == "reviewer-7"

    reviewer = AuditQueryService(
        reader,
        Principal("reviewer", frozenset({Role.REVIEWER})),
        AuthorizationPolicy(),
    )
    with pytest.raises(AuthorizationDenied):
        reviewer.search(AuditQuery())


def test_audit_query_rejects_unbounded_page_size():
    with pytest.raises(ValueError, match="pagination"):
        AuditQuery(page_size=101)
