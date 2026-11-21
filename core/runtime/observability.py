"""Structured logging helpers with mandatory credential redaction."""

from __future__ import annotations

import logging
import re

_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*)(?:bearer\s+)?\S+"),
    re.compile(r"(?i)\b(password|token|secret|cookie)=\S+"),
    re.compile(r"(?i)(://[^:/\s]+:)[^@/\s]+(@)"),
)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        message = _PATTERNS[0].sub(r"\1[REDACTED]", message)
        message = _PATTERNS[1].sub(r"\1=[REDACTED]", message)
        message = _PATTERNS[2].sub(r"\1[REDACTED]\2", message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(
        logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s",'
            '"component":"%(name)s","message":"%(message)s"}'
        )
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
