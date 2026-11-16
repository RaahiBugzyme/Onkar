"""Safety checks for the dedicated PostgreSQL test database configuration."""

import pytest
from sqlalchemy import text

from app.db_safety import validate_test_database_url
from app import database


def test_pytest_engine_targets_explicit_postgresql_test_database():
    assert database.engine.dialect.name == "postgresql"
    with database.engine.connect() as connection:
        name, _, is_superuser = connection.execute(text(
            "SELECT current_database(), current_user, "
            "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
        )).one()
    assert name.casefold().startswith("test_") or name.casefold().endswith("_test")
    assert is_superuser is False


@pytest.mark.parametrize(
    ("test_url", "application_url"),
    [
        ("postgresql://user:secret@localhost/raahi", "postgresql://user:secret@localhost/raahi"),
        ("postgresql://user:secret@localhost/raahi_test", "postgresql://user:secret@localhost/raahi_test"),
        ("sqlite:///raahi_test.db", "postgresql://user:secret@localhost/raahi"),
    ],
)
def test_unsafe_test_database_urls_are_refused(test_url, application_url):
    with pytest.raises(ValueError):
        validate_test_database_url(test_url, application_url)


def test_test_database_name_must_be_explicit():
    with pytest.raises(ValueError, match="start with 'test_' or end with '_test'"):
        validate_test_database_url("postgresql://user:secret@localhost/raahi_dev")
