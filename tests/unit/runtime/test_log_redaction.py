import logging

from core.runtime.observability import SecretRedactionFilter


def test_log_filter_redacts_credentials_and_authorization_headers():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "request Authorization: Bearer abc password=secret token=xyz",
        (),
        None,
    )

    assert SecretRedactionFilter().filter(record) is True
    rendered = record.getMessage()
    assert "abc" not in rendered
    assert "secret" not in rendered
    assert "xyz" not in rendered
    assert "[REDACTED]" in rendered
