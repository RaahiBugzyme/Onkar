"""Read-only PostgreSQL schema comparison for disposable Raahi environments.

Set RAAHI_SCHEMA_REFERENCE_URL to the fresh disposable database and
RAAHI_SCHEMA_CANDIDATE_URL to the existing-schema disposable database. The tool
accepts only the two exact approved local targets, never loads .env, and never
prints connection URLs or credentials.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL

from app.db_safety import (
    validate_phase3b_database_url,
    verify_phase3b_connection_identity,
)


REFERENCE_ENV = "RAAHI_SCHEMA_REFERENCE_URL"
CANDIDATE_ENV = "RAAHI_SCHEMA_CANDIDATE_URL"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    return str(value)


def _snapshot(
    url: URL,
    env_name: str,
    expected_database: str,
) -> tuple[str, dict[str, Any], list[str]]:
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            verify_phase3b_connection_identity(
                connection,
                expected_database=expected_database,
            )
            database_name = connection.execute(text("SELECT current_database()")).scalar_one()
            if database_name != expected_database:
                raise RuntimeError(f"{env_name} connected to an unexpected database")
            inspector = inspect(connection)
            tables: dict[str, Any] = {}
            for table in sorted(inspector.get_table_names(schema="public")):
                if table == "alembic_version":
                    continue
                columns = []
                for column in inspector.get_columns(table, schema="public"):
                    columns.append({
                        "name": column["name"],
                        "type": column["type"].compile(dialect=connection.dialect).upper(),
                        "nullable": column["nullable"],
                        "default": _json_value(column.get("default")),
                        "identity": _json_value(column.get("identity")),
                        "computed": _json_value(column.get("computed")),
                    })
                pk = inspector.get_pk_constraint(table, schema="public") or {}
                uniques = inspector.get_unique_constraints(table, schema="public")
                checks = inspector.get_check_constraints(table, schema="public")
                foreign_keys = inspector.get_foreign_keys(table, schema="public")
                indexes = inspector.get_indexes(table, schema="public")
                tables[table] = {
                    "columns": columns,
                    "primary_key": {
                        "name": pk.get("name"),
                        "columns": pk.get("constrained_columns") or [],
                    },
                    "unique_constraints": sorted(
                        ({"name": c.get("name"), "columns": c.get("column_names") or []} for c in uniques),
                        key=lambda item: (item["name"] or "", item["columns"]),
                    ),
                    "check_constraints": sorted(
                        ({"name": c.get("name"), "sql": " ".join((c.get("sqltext") or "").split())} for c in checks),
                        key=lambda item: (item["name"] or "", item["sql"]),
                    ),
                    "foreign_keys": sorted(
                        ({
                            "name": fk.get("name"),
                            "columns": fk.get("constrained_columns") or [],
                            "referred_table": fk.get("referred_table"),
                            "referred_columns": fk.get("referred_columns") or [],
                            "options": _json_value(fk.get("options") or {}),
                        } for fk in foreign_keys),
                        key=lambda item: (item["name"] or "", item["columns"]),
                    ),
                    "indexes": sorted(
                        ({
                            "name": index.get("name"),
                            "columns": index.get("column_names") or [],
                            "unique": bool(index.get("unique")),
                            "expressions": _json_value(index.get("expressions")),
                            "options": _json_value(index.get("dialect_options") or {}),
                        } for index in indexes),
                        key=lambda item: (item["name"] or "", item["columns"]),
                    ),
                }
            extensions = connection.execute(text(
                "SELECT extname, extversion FROM pg_extension ORDER BY extname"
            )).all()
            revisions = []
            if "alembic_version" in inspector.get_table_names(schema="public"):
                revisions = connection.execute(text("SELECT version_num FROM public.alembic_version ORDER BY version_num")).scalars().all()
            return database_name, {
                "tables": tables,
                "extensions": [{"name": name, "version": version} for name, version in extensions],
            }, list(revisions)
    finally:
        engine.dispose()


def main() -> int:
    reference_url = os.getenv(REFERENCE_ENV)
    candidate_url = os.getenv(CANDIDATE_ENV)
    if not reference_url or not candidate_url:
        print(f"Set {REFERENCE_ENV} and {CANDIDATE_ENV} to the approved disposable PostgreSQL URLs.", file=sys.stderr)
        return 2
    try:
        reference_target = validate_phase3b_database_url(
            reference_url,
            expected_database="test_raahi_migration_fresh_disposable",
        )
        candidate_target = validate_phase3b_database_url(
            candidate_url,
            expected_database="test_raahi_migration_existing_disposable",
        )
        ref_name, ref_schema, ref_revisions = _snapshot(
            reference_target,
            REFERENCE_ENV,
            "test_raahi_migration_fresh_disposable",
        )
        candidate_db, candidate_schema, candidate_revisions = _snapshot(
            candidate_target,
            CANDIDATE_ENV,
            "test_raahi_migration_existing_disposable",
        )
    except Exception as exc:
        print(f"Schema comparison refused or failed ({type(exc).__name__}); details suppressed.", file=sys.stderr)
        return 2

    schema_equal = ref_schema == candidate_schema
    result = {
        "reference_database": ref_name,
        "candidate_database": candidate_db,
        "schema_equal": schema_equal,
        "revision_state_equal": ref_revisions == candidate_revisions,
        "reference_revisions": ref_revisions,
        "candidate_revisions": candidate_revisions,
        "reference_table_count": len(ref_schema["tables"]),
        "candidate_table_count": len(candidate_schema["tables"]),
        "reference_extension_names": [item["name"] for item in ref_schema["extensions"]],
        "candidate_extension_names": [item["name"] for item in candidate_schema["extensions"]],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if schema_equal else 1


if __name__ == "__main__":
    raise SystemExit(main())
