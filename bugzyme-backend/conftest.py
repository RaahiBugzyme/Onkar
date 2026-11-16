"""Fail-closed PostgreSQL selection and per-test transaction isolation."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv, dotenv_values
from sqlalchemy import inspect, text

from app.db_safety import database_fingerprint, validate_test_database_url


BACKEND_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKEND_ROOT / ".env", override=False)
load_dotenv(BACKEND_ROOT / ".env.test", override=False)

_application_url_value = os.getenv("DATABASE_URL") or dotenv_values(BACKEND_ROOT / ".env").get("DATABASE_URL")
_test_url_value = os.getenv("TEST_DATABASE_URL")
try:
    _test_url = validate_test_database_url(_test_url_value, _application_url_value)
except ValueError as exc:
    raise pytest.UsageError(str(exc)) from exc
_application_fingerprint = database_fingerprint(_application_url_value)
_application_database_name = None
if _application_url_value:
    from sqlalchemy.engine import make_url
    _application_database_name = make_url(_application_url_value).database

# The test URL replaces DATABASE_URL before any test module can import app.database.
os.environ["RAAHI_TEST_MODE"] = "1"
if _application_fingerprint:
    os.environ["RAAHI_APPLICATION_DATABASE_FINGERPRINT"] = _application_fingerprint
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
del _application_url_value

_suite_lock_connection = None
_suite_lock_id = 0x524154455354


def pytest_sessionstart(session):
    """Serialize test runs that share this dedicated database."""
    global _suite_lock_connection
    if os.getenv("PYTEST_XDIST_WORKER"):
        raise pytest.UsageError("pytest-xdist is disabled for the shared raahi_test database")
    from app import database

    _suite_lock_connection = database.engine.connect()
    _suite_lock_connection.execute(
        text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": _suite_lock_id}
    )
    _suite_lock_connection.commit()


def pytest_sessionfinish(session, exitstatus):
    global _suite_lock_connection
    if _suite_lock_connection is None:
        return
    try:
        _suite_lock_connection.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _suite_lock_id}
        )
        _suite_lock_connection.commit()
    finally:
        _suite_lock_connection.close()
        _suite_lock_connection = None


def pytest_report_header():
    return f"Database safety: PostgreSQL test database '{_test_url.database}' selected; application database rejected"


@pytest.fixture(autouse=True)
def clean_dedicated_test_database():
    """Clear committed rows after each test, guarded to the named test DB."""
    from app import database

    yield

    with database.engine.begin() as connection:
        actual_name = connection.execute(text("SELECT current_database()")).scalar_one()
        if actual_name.casefold() != (_test_url.database or "").casefold():
            raise RuntimeError("Refusing test cleanup: connected database changed")
        app_name = (_application_database_name or "").casefold()
        if actual_name.casefold() == app_name:
            raise RuntimeError("Refusing test cleanup: test URL matches application database")
        inspector = inspect(connection)
        table_names = inspector.get_table_names(schema="public")
        if table_names:
            preparer = connection.dialect.identifier_preparer
            qualified = ", ".join(
                f"public.{preparer.quote(name)}" for name in table_names
            )
            connection.exec_driver_sql(
                f"TRUNCATE TABLE {qualified} RESTART IDENTITY CASCADE"
            )
