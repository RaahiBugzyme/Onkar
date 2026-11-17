"""Alembic graph checks plus an opt-in disposable-PostgreSQL integration test."""

import os
from pathlib import Path
import unittest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.db_safety import validate_phase3b_database_url


BACKEND_ROOT = Path(__file__).resolve().parent
EXPECTED_PARENTS = {
    "0ab4c9d72e61": None,
    "1d5280e25742": "0ab4c9d72e61",
    "6a4f2b8c91de": "1d5280e25742",
    "7c2f4a91d6b3": "6a4f2b8c91de",
    "3d9e71b4c2a6": "7c2f4a91d6b3",
    "8f2c1a6b4d90": "3d9e71b4c2a6",
    "a41d9e7c2b60": "8f2c1a6b4d90",
    "c73e51a2b640": "a41d9e7c2b60",
    "ba28df14c601": "c73e51a2b640",
    "d9f4b2c81a67": "ba28df14c601",
    "e12f3a4b5c6d": "d9f4b2c81a67",
    "f62a9c31e7b4": "e12f3a4b5c6d",
    "8e31a47c9d20": "f62a9c31e7b4",
    "93b7e4c18a62": "f62a9c31e7b4",
    "ca7f31d2b904": ("8e31a47c9d20", "93b7e4c18a62"),
}


class MigrationChainStructureTests(unittest.TestCase):
    def test_complete_revision_graph_has_expected_parents_and_one_head(self):
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        revisions = {revision.revision: revision for revision in script.walk_revisions()}

        self.assertEqual(set(revisions), set(EXPECTED_PARENTS))
        self.assertEqual(script.get_heads(), ["ca7f31d2b904"])
        self.assertEqual(script.get_base(), "0ab4c9d72e61")
        for revision_id, expected_parent in EXPECTED_PARENTS.items():
            with self.subTest(revision=revision_id):
                self.assertEqual(revisions[revision_id].down_revision, expected_parent)

    def test_initial_migration_installs_pgvector_before_vector_column_tables(self):
        source = (
            BACKEND_ROOT
            / "alembic"
            / "versions"
            / "0ab4c9d72e61_bootstrap_core_tables.py"
        ).read_text(encoding="utf-8")
        upgrade_body = source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
        extension_step = upgrade_body.index('op.execute("CREATE EXTENSION IF NOT EXISTS vector")')
        table_step = upgrade_body.index("_create_tables()", extension_step)
        self.assertLess(extension_step, table_step)
        self.assertIn('sa.Column("embedding", Vector(384)', source)


class DisposableMigrationIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RAAHI_RUN_DISPOSABLE_MIGRATION_INTEGRATION") == "1",
        "set the explicit integration flag to run against an empty approved disposable database",
    )
    def test_full_upgrade_head_on_empty_approved_disposable_database(self):
        target = validate_phase3b_database_url(
            os.environ.get("RAAHI_ALEMBIC_DATABASE_URL"),
            expected_database="test_raahi_migration_fresh_disposable",
        )
        engine = create_engine(target, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                table_names = set(inspect(connection).get_table_names(schema="public"))
                self.assertEqual(
                    table_names,
                    set(),
                    "the integration target must be empty before the full migration run",
                )
        finally:
            engine.dispose()

        command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")

        engine = create_engine(target, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                inspector = inspect(connection)
                self.assertIn("alembic_version", inspector.get_table_names(schema="public"))
                revision = connection.execute(text(
                    "SELECT version_num FROM public.alembic_version"
                )).scalar_one()
                self.assertEqual(revision, "ca7f31d2b904")
                self.assertTrue(connection.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                )).scalar_one())
                self.assertIn(
                    "user_memories",
                    inspector.get_table_names(schema="public"),
                )
                columns = inspector.get_columns("user_memories", schema="public")
                embedding = next(column for column in columns if column["name"] == "embedding")
                self.assertEqual(
                    embedding["type"].compile(dialect=connection.dialect).upper(),
                    "VECTOR(384)",
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
