from logging.config import fileConfig
import os

from sqlalchemy import engine_from_config
from sqlalchemy import text
from sqlalchemy import pool
from alembic import context
from app.db_safety import (
    end_phase3b_identity_transaction,
    validate_local_development_migration_url,
    validate_phase3b_database_url,
    validate_production_database_url,
    verify_local_development_migration_identity,
    verify_phase3b_connection_identity,
    verify_production_connection_identity,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic must target an explicitly selected database; never fall back to the
# application .env or the URL in alembic.ini. Validate the exact target before
# importing models: app.database loads .env and creates an Engine as an import
# side effect, so bind that process-local Engine to the same validated target.
# The local-development path is opt-in and restricted to raahi on localhost;
# the disposable migration path retains its existing exact target guard.
local_dev_migration_url = os.environ.get("RAAHI_LOCAL_DEV_MIGRATION_URL")
disposable_migration_url = os.environ.get("RAAHI_ALEMBIC_DATABASE_URL")
production_migration_url = os.environ.get("RAAHI_PRODUCTION_ALEMBIC_DATABASE_URL")
production_opt_in = os.environ.get("RAAHI_PRODUCTION_MIGRATIONS")
selected_targets = sum(bool(value) for value in (
    local_dev_migration_url,
    disposable_migration_url,
    production_migration_url,
))
if selected_targets > 1:
    raise RuntimeError("Select only one explicit Alembic target; details suppressed")
if production_opt_in not in (None, "enabled"):
    raise RuntimeError("Production migration opt-in has an invalid value")
if production_opt_in == "enabled" and not production_migration_url:
    raise RuntimeError("Production migration opt-in requires its dedicated target URL")
if production_migration_url and production_opt_in != "enabled":
    raise RuntimeError("Production migrations require explicit opt-in")

local_dev_migration = bool(local_dev_migration_url)
production_migration = bool(production_migration_url)
production_expected_database = None
production_expected_role = None
if production_migration:
    production_expected_host = os.environ.get("RAAHI_PRODUCTION_DB_HOST")
    production_expected_database = os.environ.get("RAAHI_PRODUCTION_DB_NAME")
    production_expected_username = os.environ.get("RAAHI_PRODUCTION_DB_USER")
    production_expected_role = os.environ.get("RAAHI_PRODUCTION_DB_ROLE")
    validated_migration_url = validate_production_database_url(
        production_migration_url,
        expected_host=production_expected_host,
        expected_database=production_expected_database,
        expected_username=production_expected_username,
        expected_role=production_expected_role,
    )
    expected_database = production_expected_database
elif local_dev_migration:
    validated_migration_url = validate_local_development_migration_url(
        local_dev_migration_url
    )
    expected_database = "raahi"
else:
    validated_migration_url = validate_phase3b_database_url(
        disposable_migration_url,
        expected_database="test_raahi_migration_fresh_disposable",
    )
    expected_database = "test_raahi_migration_fresh_disposable"
os.environ.pop("RAAHI_TEST_MODE", None)
os.environ["DATABASE_URL"] = validated_migration_url.render_as_string(hide_password=False)
config.set_main_option(
    "sqlalchemy.url",
    validated_migration_url.render_as_string(hide_password=False).replace("%", "%%"),
)

# Import metadata only after DATABASE_URL is pinned to the validated target.
from app import models  # noqa: E402,F401
from app.database import Base  # noqa: E402

target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        connection = connectable.connect()
    except Exception as exc:
        raise RuntimeError(
            f"Could not connect to the approved Phase 3B database ({type(exc).__name__}); details suppressed."
        ) from None

    with connection:
        if production_migration:
            verify_production_connection_identity(
                connection,
                expected_database=production_expected_database,
                expected_role=production_expected_role,
            )
        elif local_dev_migration:
            verify_local_development_migration_identity(connection)
        else:
            verify_phase3b_connection_identity(
                connection,
                expected_database=expected_database,
            )
        # The identity SELECT autobegins a SQLAlchemy transaction. End only
        # that read-only preflight transaction so Alembic can own its migration
        # transaction instead of treating it as externally managed.
        end_phase3b_identity_transaction(connection)
        if connection.in_transaction():
            raise RuntimeError("Identity-check transaction remained open before Alembic configuration")
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            if local_dev_migration or production_migration:
                # Serialize local-development and explicitly approved production
                # upgrades; disposable migration targets retain their prior behavior.
                connection.execute(text("SELECT pg_advisory_xact_lock(7419882804270007)"))
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
