from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from core.adapters.persistence.database import create_database_engine


@pytest.fixture(scope="session")
def postgres_url() -> str:
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def postgres_engine(postgres_url: str) -> Engine:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_database_engine(postgres_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(postgres_engine: Engine) -> None:
    yield
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE story_generations, audit_entries, publish_attempts, publish_targets, "
                "artifacts, work_items, job_transitions, job_commands, jobs, "
                "channel_profile_revisions, channel_profiles "
                "RESTART IDENTITY CASCADE"
            )
        )
