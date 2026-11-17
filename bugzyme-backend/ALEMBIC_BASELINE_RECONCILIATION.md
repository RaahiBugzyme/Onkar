# Alembic bootstrap, validation, and production initialization

## Current migration graph

The repository contains 15 revisions and one head, `ca7f31d2b904`. The graph branches after `f62a9c31e7b4` and merges at the head:

```text
0ab4c9d72e61 (base)
  -> 1d5280e25742
  -> 6a4f2b8c91de
  -> 7c2f4a91d6b3
  -> 3d9e71b4c2a6
  -> 8f2c1a6b4d90
  -> a41d9e7c2b60
  -> c73e51a2b640
  -> ba28df14c601
  -> d9f4b2c81a67
  -> e12f3a4b5c6d
  -> f62a9c31e7b4
       |-> 8e31a47c9d20 --+
       |-> 93b7e4c18a62 --+-> ca7f31d2b904 (head)
```

The base revision creates `users`, `chats`, `messages`, and `user_memories`, and ensures their core indexes. It executes `CREATE EXTENSION IF NOT EXISTS vector` before table creation; `user_memories.embedding` is `VECTOR(384)`. Later revisions add message attachment/reaction fields and tables, profile and consent fields, dating tables, notification/recovery tables, and match-result provenance. The match-result revision backfills null provenance to `legacy`. The merge revision itself is a no-op.

`ca7f31d2b904` is the actual head. The earlier guide text that named `93b7e4c18a62` as head omitted the AI provider consent branch and merge revision.

## pgvector and Supabase compatibility

The extension is named `vector`; the application column uses 384 dimensions. Supabase documents enabling pgvector in the Extensions dashboard or with `CREATE EXTENSION vector`, commonly in schema `extensions`, and documents vector columns such as `extensions.vector(384)`. The base migration intentionally creates the extension if missing, then declares the SQLAlchemy `Vector(384)` type without a schema qualifier. Before production, validate that the Supabase connection's `search_path` can resolve the extension's schema and that the migration role may create the extension when it is absent. The migration must fail closed if the extension/type cannot be used; do not work around that failure by changing production search paths or schema state manually during the migration.

The opt-in integration test checks that the extension is initially absent, the full chain installs it, and the resulting column compiles as `VECTOR(384)`. A local disposable test cannot prove Supabase's role permissions or exact extension schema/search path; that remains a required reviewed preflight before production initialization.

## Target safeguards

Alembic has three mutually exclusive explicit targets:

- `RAAHI_LOCAL_DEV_MIGRATION_URL`: exact local `raahi` database, local `postgres` role, loopback server.
- `RAAHI_ALEMBIC_DATABASE_URL`: one of the explicitly approved local disposable migration databases, restricted migration role, loopback server.
- Production: requires `RAAHI_PRODUCTION_MIGRATIONS=enabled`, `RAAHI_PRODUCTION_ALEMBIC_DATABASE_URL`, and independently supplied expected values `RAAHI_PRODUCTION_DB_HOST`, `RAAHI_PRODUCTION_DB_NAME`, `RAAHI_PRODUCTION_DB_USER`, and `RAAHI_PRODUCTION_DB_ROLE`. The URL must exactly match that Supabase host/database/login username, use the psycopg2 PostgreSQL driver, include a password, and require TLS through `sslmode=require`, `verify-ca`, or `verify-full`. The login username may be the effective role for a direct endpoint, or `<role>.<project-ref>` for an exact Supavisor pooler host. After connecting, Alembic checks `current_database()`, `current_user`, and psycopg2's client-side `ssl_in_use` state before loading migrations. It does not use `pg_stat_ssl`, which can describe the pooler's server-side connection rather than the application's TLS session.

Only one target may be selected. Alembic never takes the production URL from the application `.env`. Local-development and disposable checks remain separate and retain their existing target allowlists. Keep the production URL and password in the deployment secret store; the four expected-identity values are non-secret but must be set to the exact project values independently of the URL. Do not use a pooled or direct host other than the exact approved host.

## Automated tests and disposable full-chain run

The unit tests below make no database connections:

```powershell
cd bugzyme-backend
python -m unittest test_migration_target_safety test_migration_chain.MigrationChainStructureTests
```

The full-chain integration test is opt-in. It accepts only `test_raahi_migration_fresh_disposable` on loopback with role `raahi_migration_test` and refuses a database containing public tables. If `vector` is absent, the base migration must install it; if it is already present, the migration's `IF NOT EXISTS` path must resolve and use it. The test then verifies the recorded head, extension, and vector column. Provision that empty disposable PostgreSQL database separately with the restricted test role and, when needed, extension permission. Do not point these variables at Supabase or at `raahi_test`.

```powershell
$env:RAAHI_ALEMBIC_DATABASE_URL = "<postgresql+psycopg2 URL for localhost:5432/test_raahi_migration_fresh_disposable using raahi_migration_test>"
$env:RAAHI_RUN_DISPOSABLE_MIGRATION_INTEGRATION = "1"
python -m unittest test_migration_chain.DisposableMigrationIntegrationTests
Remove-Item Env:RAAHI_ALEMBIC_DATABASE_URL
Remove-Item Env:RAAHI_RUN_DISPOSABLE_MIGRATION_INTEGRATION
```

The fresh database test follows the complete 15-revision chain, including both branch parents and the merge. The URL must not contain a password copied into shell history; supply it through a secure local secret mechanism. The regular test suite's `conftest.py` independently requires `TEST_DATABASE_URL` and connects to that named test database, so do not run broad pytest commands without first verifying that variable identifies a disposable database.

For existing-schema comparison, use two distinct disposable local databases only:

```powershell
$env:RAAHI_SCHEMA_REFERENCE_URL = "<approved fresh disposable URL>"
$env:RAAHI_SCHEMA_CANDIDATE_URL = "<approved existing-schema disposable URL>"
python -m app.schema_compare
```

The comparator is read-only, rejects other targets, and compares public tables, columns/defaults, constraints, foreign keys, indexes, extensions, and Alembic revision state. A clean Supabase database with zero public tables is not an adopted existing schema; initialize it through the reviewed fresh-database production procedure below.

## Backup, rollback, and recovery

Take and verify a logical export before the first production schema change, then store it off-host with restrictive permissions. Supabase Free projects do not have automatic daily backups; Supabase recommends manual exports. The Supabase CLI can dump schema and data separately (its default dump is schema-only and excludes Supabase-managed schemas). Run it from a trusted workstation with the CLI and its Docker dependency already available:

```bash
umask 077
supabase db dump --remote="$PROJECT_REF" -f raahi-preinit-schema.sql
supabase db dump --remote="$PROJECT_REF" --data-only -f raahi-preinit-data.sql
```

Verify the dump files are non-empty, inspectable, and stored outside the EC2 instance before proceeding. If a provider-managed backup is available on the current plan, record its restore point as an additional recovery option. Do not enable paid backup/PITR features solely for this test deployment.

Most migration downgrades intentionally preserve additive columns, indexes, or data; the base migration's downgrade is a no-op. **Alembic downgrade is not a rollback plan.** On a failed migration, stop, capture the error and current revision, and choose a reviewed forward repair or restore the pre-change backup. A restore replaces current database state and may require downtime. The database migrations do not back up Supabase Storage objects.

## Production initialization sequence — stop before applying

Production initialization is currently not authorized by these instructions and must remain a separate operator-reviewed action. The sequence is:

1. Confirm the database is the intended Supabase project and still has no application tables or prior Alembic revision; capture a fresh logical backup and verify it. A pre-initialization dump of the empty `public` schema is only a snapshot of that schema; it is not a full Supabase project backup and does not include Auth, Storage objects, or provider-managed state.
2. Complete the full-chain integration test on a disposable local PostgreSQL database and review the resulting schema, indexes, extensions, and head `ca7f31d2b904`.
3. Confirm Supabase's exact host, database, login username, and effective role from its connection settings and a read-only connection. Securely set the dedicated production URL and matching independent expected identity values. Require TLS and confirm the migration role can resolve and use pgvector. If the extension is absent and the role cannot create it, an authorized Supabase administrator must enable the supported extension before Alembic runs; the migration guard must not be bypassed.
4. Review the target preflight output, backup location, migration diff, and expected extension permissions. Stop for explicit operator authorization.
5. Only after that authorization, the reviewed production target path may run the normal command from `bugzyme-backend`:

   ```bash
   alembic upgrade head
   ```

6. Read-only verify the final Alembic head, expected tables/constraints/indexes, `vector` extension, and `user_memories.embedding` dimension. Do not use `stamp`.

No production command should be run as part of unit/integration test execution. No Supabase production connection is made by the repository's automated test suite.
