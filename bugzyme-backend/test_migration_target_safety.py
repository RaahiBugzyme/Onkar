"""Database-target guard tests; this module does not connect to PostgreSQL."""

import unittest

from sqlalchemy.engine import URL

from app.db_safety import (
    end_phase3b_identity_transaction,
    validate_local_development_migration_url,
    validate_phase3b_database_url,
    validate_production_database_url,
    verify_local_development_migration_identity,
    verify_phase3b_connection_identity,
    verify_production_connection_identity,
)


def _url(database, **overrides):
    values = {
        "drivername": "postgresql+psycopg2",
        "username": "raahi_migration_test",
        "password": "test-only-placeholder",
        "host": "localhost",
        "port": 5432,
        "database": database,
    }
    values.update(overrides)
    return URL.create(**values)


def _production_url(**overrides):
    values = {
        "drivername": "postgresql+psycopg2",
        "username": "postgres.projectref",
        "password": "test-only-placeholder",
        "host": "aws-1-region.pooler.supabase.com",
        "port": 5432,
        "database": "postgres",
        "query": {"sslmode": "require"},
    }
    values.update(overrides)
    return URL.create(**values)


class _Result:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class _Connection:
    def __init__(self, row, *, ssl_in_use=False):
        self.row = row
        self._in_transaction = False
        self.connection = self
        self.driver_connection = self
        self.info = type("ConnectionInfo", (), {"ssl_in_use": ssl_in_use})()

    def execute(self, _statement):
        self._in_transaction = True
        return _Result(self.row)

    def in_transaction(self):
        return self._in_transaction

    def rollback(self):
        self._in_transaction = False


class MigrationTargetSafetyTests(unittest.TestCase):
    def test_accepts_only_the_two_approved_urls(self):
        for database in (
            "test_raahi_migration_fresh_disposable",
            "test_raahi_migration_existing_disposable",
        ):
            with self.subTest(database=database):
                parsed = validate_phase3b_database_url(
                    _url(database), expected_database=database
                )
                self.assertEqual(parsed.database, database)

    def test_rejects_application_test_and_unapproved_databases(self):
        for database in ("raahi", "raahi_test", "bugzyme", "raahi_test_disposable"):
            with self.subTest(database=database), self.assertRaises(ValueError):
                validate_phase3b_database_url(
                    _url(database),
                    expected_database="test_raahi_migration_fresh_disposable",
                )

    def test_rejects_unexpected_driver_host_port_role_and_options(self):
        database = "test_raahi_migration_fresh_disposable"
        invalid_urls = (
            _url(database, drivername="postgresql"),
            _url(database, host="db.example.invalid"),
            _url(database, host="127.0.0.1"),
            _url(database, port=5433),
            _url(database, username="application_role"),
            _url(database, password=None),
            _url(database, query={"sslmode": "disable"}),
        )
        for candidate in invalid_urls:
            with self.subTest(candidate=candidate.database), self.assertRaises(ValueError):
                validate_phase3b_database_url(
                    candidate, expected_database=database
                )

    def test_rejects_missing_or_invalid_url_without_echoing_it(self):
        for candidate in (None, "not-a-url-secret-placeholder"):
            with self.subTest(candidate_is_missing=candidate is None), self.assertRaises(ValueError):
                validate_phase3b_database_url(
                    candidate,
                    expected_database="test_raahi_migration_fresh_disposable",
                )

    def test_rejects_wrong_expected_database(self):
        with self.assertRaises(ValueError):
            validate_phase3b_database_url(
                _url("raahi"), expected_database="raahi"
            )

    def test_live_identity_guard_accepts_ipv4_loopback(self):
        self._assert_connection_accepted("127.0.0.1")

    def test_live_identity_guard_accepts_ipv6_loopback(self):
        for address in ("::1", "::1/128"):
            with self.subTest(address=address):
                self._assert_connection_accepted(address)

    def _assert_connection_accepted(self, address):
        connection = _Connection((
            "test_raahi_migration_fresh_disposable",
            "raahi_migration_test",
            address,
            5432,
        ))
        verify_phase3b_connection_identity(connection, expected_database="test_raahi_migration_fresh_disposable")

    def test_identity_preflight_transaction_is_ended_before_configuration(self):
        connection = _Connection((
            "test_raahi_migration_fresh_disposable",
            "raahi_migration_test",
            "::1/128",
            5432,
        ))

        verify_phase3b_connection_identity(
            connection,
            expected_database="test_raahi_migration_fresh_disposable",
        )
        self.assertTrue(connection.in_transaction(), "identity SELECT should reproduce SQLAlchemy autobegin")

        end_phase3b_identity_transaction(connection)

        self.assertFalse(connection.in_transaction(), "Alembic must configure with no external transaction")

    def test_live_identity_guard_rejects_wrong_database_role_host_or_port(self):
        invalid_rows = (
            ("raahi", "raahi_migration_test", "127.0.0.1", 5432),
            ("test_raahi_migration_fresh_disposable", "postgres", "127.0.0.1", 5432),
            ("test_raahi_migration_fresh_disposable", "raahi_migration_test", "192.0.2.8", 5432),
            ("test_raahi_migration_fresh_disposable", "raahi_migration_test", "2001:db8::1", 5432),
            ("test_raahi_migration_fresh_disposable", "raahi_migration_test", "127.0.0.1", 5433),
            ("test_raahi_migration_fresh_disposable", "raahi_migration_test", None, 5432),
            ("test_raahi_migration_fresh_disposable", "raahi_migration_test", "not-an-ip-address", 5432),
            ("test_raahi_migration_fresh_disposable", "raahi_migration_test", "::1/64", 5432),
        )
        for row in invalid_rows:
            with self.subTest(database=row[0], role=row[1]), self.assertRaises(RuntimeError):
                verify_phase3b_connection_identity(
                    _Connection(row),
                    expected_database="test_raahi_migration_fresh_disposable",
                )

    def test_local_development_migration_target_is_exact_and_loopback_only(self):
        parsed = validate_local_development_migration_url(
            URL.create(
                "postgresql",
                username="postgres",
                password="test-only-placeholder",
                host="localhost",
                port=5432,
                database="raahi",
            )
        )
        self.assertEqual(parsed.database, "raahi")
        invalid_urls = (
            None,
            _url("raahi"),
            URL.create("postgresql", username="postgres", password="x", host="localhost", port=5432, database="raahi_test"),
            URL.create("postgresql", username="postgres", password="x", host="db.example.invalid", port=5432, database="raahi"),
            URL.create("postgresql", username="postgres", password="x", host="localhost", port=5433, database="raahi"),
            URL.create("postgresql", username="raahi_app", password="x", host="localhost", port=5432, database="raahi"),
            URL.create("postgresql", username="postgres", password=None, host="localhost", port=5432, database="raahi"),
            URL.create("postgresql", username="postgres", password="x", host="localhost", port=5432, database="raahi", query={"sslmode": "disable"}),
        )
        for candidate in invalid_urls:
            with self.subTest(candidate_type=type(candidate).__name__), self.assertRaises(ValueError):
                validate_local_development_migration_url(candidate)

    def test_local_development_identity_accepts_loopback_and_rejects_other_targets(self):
        for address in ("127.0.0.1", "::1", "::1/128"):
            with self.subTest(address=address):
                verify_local_development_migration_identity(
                    _Connection(("raahi", "postgres", address, 5432))
                )
        for row in (
            ("raahi_test", "postgres", "127.0.0.1", 5432),
            ("postgres", "postgres", "127.0.0.1", 5432),
            ("raahi", "raahi_migration_test", "127.0.0.1", 5432),
            ("raahi", "postgres", "192.0.2.8", 5432),
            ("raahi", "postgres", "127.0.0.1", 5433),
        ):
            with self.subTest(row=row), self.assertRaises(RuntimeError):
                verify_local_development_migration_identity(_Connection(row))

    def test_production_url_requires_exact_supabase_host_database_user_and_tls(self):
        approved = validate_production_database_url(
            _production_url(),
            expected_host="aws-1-region.pooler.supabase.com",
            expected_database="postgres",
            expected_username="postgres.projectref",
            expected_role="postgres",
        )
        self.assertEqual(approved.host, "aws-1-region.pooler.supabase.com")

        invalid_cases = (
            (_production_url(host="other.pooler.supabase.com"), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "postgres"),
            (_production_url(database="other"), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "postgres"),
            (_production_url(username="other_role"), "aws-1-region.pooler.supabase.com", "postgres", "other_role", "postgres"),
            (_production_url(host="db.example.invalid"), "db.example.invalid", "postgres", "postgres.projectref", "postgres"),
            (_production_url(query={"sslmode": "disable"}), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "postgres"),
            (_production_url(query={}), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "postgres"),
            (_production_url(query={"sslmode": "require", "connect_timeout": "2"}), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "postgres"),
            (_production_url(drivername="postgresql"), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "postgres"),
            (_production_url(), "aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", "wrong_role"),
        )
        for candidate, host, database, username, role in invalid_cases:
            with self.subTest(host=candidate.host, database=candidate.database), self.assertRaises(ValueError):
                validate_production_database_url(
                    candidate,
                    expected_host=host,
                    expected_database=database,
                    expected_username=username,
                    expected_role=role,
                )

        for expected in (
            (None, "postgres", "postgres.projectref", "postgres"),
            ("aws-1-region.pooler.supabase.com", None, "postgres.projectref", "postgres"),
            ("aws-1-region.pooler.supabase.com", "postgres", None, "postgres"),
            ("aws-1-region.pooler.supabase.com", "postgres", "postgres.projectref", None),
        ):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                validate_production_database_url(
                    _production_url(),
                    expected_host=expected[0],
                    expected_database=expected[1],
                    expected_username=expected[2],
                    expected_role=expected[3],
                )

    def test_production_live_identity_requires_expected_role_database_and_ssl(self):
        verify_production_connection_identity(
            _Connection(("postgres", "postgres"), ssl_in_use=True),
            expected_database="postgres",
            expected_role="postgres",
        )
        for row in (
            ("other", "postgres"),
            ("postgres", "other_role"),
            ("postgres", "postgres"),
        ):
            with self.subTest(row=row), self.assertRaises(RuntimeError):
                verify_production_connection_identity(
                    _Connection(row),
                    expected_database="postgres",
                    expected_role="postgres",
                )
        with self.assertRaises(RuntimeError):
            verify_production_connection_identity(
                _Connection(("postgres", "postgres"), ssl_in_use=False),
                expected_database="postgres",
                expected_role="postgres",
            )


if __name__ == "__main__":
    unittest.main()
