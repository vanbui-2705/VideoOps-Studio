"""SQLAlchemy engine construction kept outside the application core."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url


def create_database_engine(
    database_url: str,
    *,
    pool_size: int = 3,
    max_overflow: int = 2,
    echo: bool = False,
) -> Engine:
    """Create a small synchronous PostgreSQL pool suitable for hosted databases."""
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise ValueError("Module 3 requires a PostgreSQL database URL")
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    local_hosts = {None, "localhost", "127.0.0.1", "::1"}
    secure_modes = {"require", "verify-ca", "verify-full"}
    if url.host not in local_hosts and url.query.get("sslmode") not in secure_modes:
        raise ValueError("Remote PostgreSQL connections must set sslmode=require")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        echo=echo,
    )
