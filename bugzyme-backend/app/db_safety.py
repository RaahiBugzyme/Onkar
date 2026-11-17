"""Small, side-effect-free validation helpers for test database selection."""

import hashlib
import ipaddress
import re

from sqlalchemy import text
from sqlalchemy.engine import Connection, URL, make_url


_TEST_DATABASE_NAME = re.compile(r"^(?:test[_-].+|.+[_-]test)$", re.IGNORECASE)
_MIGRATION_ROLE = "raahi_migration_test"
_MIGRATION_HOST = "localhost"
_MIGRATION_PORT = 5432
_MIGRATION_DATABASES = {
    "test_raahi_migration_fresh_disposable",
    "test_raahi_migration_existing_disposable",
}
_LOCAL_DEV_DATABASE = "raahi"
_LOCAL_DEV_ROLE = "postgres"
_PRODUCTION_SSL_MODES = {"require", "verify-ca", "verify-full"}


def validate_production_database_url(
    url_value: str | URL | None,
    *,
    expected_host: str | None,
    expected_database: str | None,
    expected_username: str | None,
    expected_role: str | None,
) -> URL:
    """Validate a narrowly allowlisted Supabase URL before opening a connection.

    The expected identity is supplied independently from the URL. No wildcard
    host matching is used, and only a TLS-enabled sslmode query parameter is
    accepted. The URL itself must be provided through the dedicated production
    Alembic variable, never inferred from the application .env.
    """
    if not all((expected_host, expected_database, expected_username, expected_role)):
        raise ValueError("Production database identity is incomplete")
    if not url_value:
        raise ValueError("Production Alembic database URL is not configured")
    try:
        url = url_value if isinstance(url_value, URL) else make_url(url_value)
    except Exception:
        raise ValueError("Production database URL is invalid; details suppressed") from None

    host = (url.host or "").rstrip(".").casefold()
    expected_host_normalized = (expected_host or "").rstrip(".").casefold()
    if not (
        host == expected_host_normalized
        and (host.endswith(".supabase.com") or host.endswith(".supabase.co"))
    ):
        raise ValueError("Production database host is not the exact approved Supabase host")
    if url.drivername != "postgresql+psycopg2":
        raise ValueError("Production database URL must use postgresql+psycopg2")
    if url.database != expected_database:
        raise ValueError("Production database URL has an unexpected database")
    if url.username != expected_username or not url.password:
        raise ValueError("Production database URL has an unexpected username or missing password")
    direct_login = url.username == expected_role
    pooler_login = (
        host.endswith(".pooler.supabase.com")
        and url.username.startswith(f"{expected_role}.")
        and len(url.username) > len(expected_role) + 1
    )
    if not (direct_login or pooler_login):
        raise ValueError("Production database login does not map to the expected database role")
    if set(url.query) != {"sslmode"} or url.query.get("sslmode") not in _PRODUCTION_SSL_MODES:
        raise ValueError("Production database URL must require PostgreSQL TLS")
    if isinstance(url_value, str) and "#" in url_value:
        raise ValueError("Production database URL fragments are not allowed")
    return url


def verify_production_connection_identity(
    connection: Connection,
    *,
    expected_database: str,
    expected_role: str,
) -> None:
    """Verify the effective database role and client-side TLS negotiation.

    Supavisor can expose the pooler's effective database role as ``current_user``
    rather than the project-qualified login username. Also, ``pg_stat_ssl`` can
    describe the pooler's backend connection instead of the application's
    client-to-pooler TLS session, so inspect psycopg2's negotiated connection.
    """
    row = connection.execute(text("""
        SELECT current_database(), current_user
    """)).one()
    database_name, role_name = row
    driver_connection = connection.connection.driver_connection
    ssl_enabled = bool(driver_connection.info.ssl_in_use)
    if (
        database_name != expected_database
        or role_name != expected_role
        or not ssl_enabled
    ):
        raise RuntimeError("Connected PostgreSQL identity or TLS state is not approved")


def validate_phase3b_database_url(
    url_value: str | URL | None,
    *,
    expected_database: str,
) -> URL:
    """Validate an exact Phase 3B target before opening any DB connection."""
    if expected_database not in _MIGRATION_DATABASES:
        raise ValueError("Requested database is not an approved Phase 3B target")
    if not url_value:
        raise ValueError("Required Phase 3B database URL is not configured")
    try:
        url = url_value if isinstance(url_value, URL) else make_url(url_value)
    except Exception:
        raise ValueError("Phase 3B database URL is invalid; details suppressed") from None

    if url.drivername != "postgresql+psycopg2":
        raise ValueError("Phase 3B database URL must use postgresql+psycopg2")
    if url.host != _MIGRATION_HOST or url.port != _MIGRATION_PORT:
        raise ValueError("Phase 3B database URL has an unapproved host or port")
    if url.username != _MIGRATION_ROLE or not url.password:
        raise ValueError("Phase 3B database URL must use the restricted migration role")
    if url.database != expected_database:
        raise ValueError("Phase 3B database URL targets an unapproved database")
    has_fragment = isinstance(url_value, str) and "#" in url_value
    if url.query or has_fragment:
        raise ValueError("Phase 3B database URL options are not allowed")
    return url


def verify_phase3b_connection_identity(
    connection: Connection,
    *,
    expected_database: str,
) -> None:
    """Verify the live PostgreSQL endpoint, database, and authenticated role."""
    if expected_database not in _MIGRATION_DATABASES:
        raise RuntimeError("Requested database is not an approved Phase 3B target")
    row = connection.execute(text("""
        SELECT current_database(), current_user,
               inet_server_addr()::text, inet_server_port()
    """)).one()
    database_name, role_name, server_address, server_port = row
    try:
        parsed_address = ipaddress.ip_interface(server_address) if server_address else None
        is_loopback = bool(
            parsed_address
            and parsed_address.ip.is_loopback
            and parsed_address.network.prefixlen == parsed_address.ip.max_prefixlen
        )
    except ValueError:
        is_loopback = False
    if (
        database_name != expected_database
        or role_name != _MIGRATION_ROLE
        or not is_loopback
        or server_port != _MIGRATION_PORT
    ):
        raise RuntimeError("Connected PostgreSQL identity is not an approved Phase 3B target")


def validate_local_development_migration_url(url_value: str | URL | None) -> URL:
    """Accept only the explicitly authorized loopback Raahi development database."""
    if not url_value:
        raise ValueError("RAAHI_LOCAL_DEV_MIGRATION_URL is required")
    try:
        url = url_value if isinstance(url_value, URL) else make_url(url_value)
    except Exception:
        raise ValueError("Local development migration URL is invalid; details suppressed") from None

    if url.drivername != "postgresql":
        raise ValueError("Local development migration URL must use PostgreSQL")
    if url.host != _MIGRATION_HOST or url.port not in (None, _MIGRATION_PORT):
        raise ValueError("Local development migration URL has an unapproved host or port")
    if url.username != _LOCAL_DEV_ROLE or not url.password:
        raise ValueError("Local development migration URL must use the configured local role")
    if url.database != _LOCAL_DEV_DATABASE:
        raise ValueError("Local development migration URL targets an unapproved database")
    has_fragment = isinstance(url_value, str) and "#" in url_value
    if url.query or has_fragment:
        raise ValueError("Local development migration URL options are not allowed")
    return url


def verify_local_development_migration_identity(connection: Connection) -> None:
    """Confirm the live target is exactly Raahi's local development database."""
    row = connection.execute(text("""
        SELECT current_database(), current_user,
               inet_server_addr()::text, inet_server_port()
    """)).one()
    database_name, role_name, server_address, server_port = row
    try:
        parsed_address = ipaddress.ip_interface(server_address) if server_address else None
        is_loopback = bool(
            parsed_address
            and parsed_address.ip.is_loopback
            and parsed_address.network.prefixlen == parsed_address.ip.max_prefixlen
        )
    except ValueError:
        is_loopback = False
    if (
        database_name != _LOCAL_DEV_DATABASE
        or role_name != _LOCAL_DEV_ROLE
        or not is_loopback
        or server_port != _MIGRATION_PORT
    ):
        raise RuntimeError("Connected PostgreSQL identity is not the approved local development target")


def end_phase3b_identity_transaction(connection: Connection) -> None:
    """Roll back only the identity SELECT transaction on a fresh Alembic connection."""
    if connection.in_transaction():
        connection.rollback()
    if connection.in_transaction():
        raise RuntimeError("Identity-check transaction remained open")


def database_fingerprint(url: str | URL | None) -> str | None:
    """Return a non-secret identity for a PostgreSQL host/port/database tuple."""
    if not url:
        return None
    try:
        parsed = url if isinstance(url, URL) else make_url(url)
    except Exception as exc:
        raise ValueError("Database URL is invalid; credentials were not displayed") from exc
    if not parsed.drivername.startswith("postgresql"):
        return None
    identity = "|".join((
        (parsed.host or "localhost").casefold(),
        str(parsed.port or 5432),
        (parsed.database or "").casefold(),
    ))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def validate_test_database_url(
    test_url: str | None,
    application_url: str | None = None,
    application_fingerprint: str | None = None,
) -> URL:
    """Return a safe PostgreSQL test URL or raise without exposing credentials."""
    if not test_url:
        raise ValueError("TEST_DATABASE_URL must be explicitly configured for pytest")

    try:
        parsed_test = make_url(test_url)
        parsed_app = make_url(application_url) if application_url else None
    except Exception as exc:
        raise ValueError("Database URL is invalid; credentials were not displayed") from exc

    if not parsed_test.drivername.startswith("postgresql"):
        raise ValueError("TEST_DATABASE_URL must use PostgreSQL")

    test_name = (parsed_test.database or "").strip()
    if not _TEST_DATABASE_NAME.fullmatch(test_name):
        raise ValueError("Test database name must start with 'test_' or end with '_test'")

    expected_fingerprint = application_fingerprint or database_fingerprint(parsed_app)
    if expected_fingerprint and database_fingerprint(parsed_test) == expected_fingerprint:
        raise ValueError("TEST_DATABASE_URL points to the application database")

    return parsed_test
