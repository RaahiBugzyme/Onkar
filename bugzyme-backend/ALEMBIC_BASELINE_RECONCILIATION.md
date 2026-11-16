# Alembic bootstrap and reconciliation procedure

## Graph and bootstrap coverage

The graph is a single chain:

`0ab4c9d72e61 → 1d5280e25742 → 6a4f2b8c91de → 7c2f4a91d6b3 → 3d9e71b4c2a6 → 8f2c1a6b4d90 → a41d9e7c2b60 → c73e51a2b640 → ba28df14c601 → d9f4b2c81a67 → e12f3a4b5c6d → f62a9c31e7b4 → 93b7e4c18a62`

The prior chain created the recovery, notification, reaction, dating, consent, and match-result tables, but did not create the foundational `users`, `chats`, `messages`, or `user_memories` tables. The new root revision creates those tables and their core constraints/indexes. It installs the PostgreSQL `vector` extension required by `user_memories.embedding`; the migration role needs permission to install that extension or an administrator must install it first.

Revision `1d5280e25742` now ensures indexes by definition and skips equivalent existing indexes. This avoids both the duplicate message-index failure and redundant chat indexes on databases initialized with `Base.metadata.create_all`. It retains its index behavior while using the canonical metadata index names. Its downgrade is intentionally non-destructive.

`alembic/env.py` now requires `RAAHI_ALEMBIC_DATABASE_URL`; Alembic no longer falls back to `.env`’s application URL or the development URL in `alembic.ini`.

## Fresh database validation procedure

Provision a disposable empty PostgreSQL database and a migration role that can create tables and install/use `vector`. Set `RAAHI_ALEMBIC_DATABASE_URL` explicitly, then run:

```powershell
python -m alembic upgrade head
```

Confirm that revision `93b7e4c18a62` is recorded, all tables in `app.models.Base.metadata` exist, and each table’s columns, types, nullability, primary/unique/check constraints, foreign keys, and indexes match the expected schema. Run the backend smoke tests against that disposable database only.

## Existing schema comparison and adoption

The comparator is read-only and requires two distinct disposable PostgreSQL URLs:

```powershell
$env:RAAHI_SCHEMA_REFERENCE_URL = "<fresh-reference-url-ending-in-_disposable>"
$env:RAAHI_SCHEMA_CANDIDATE_URL = "<existing-schema-simulation-url-ending-in-_disposable>"
python -m app.schema_compare
```

It compares tables, column types/nullability/defaults, primary keys, unique and check constraints, foreign keys and delete actions, complete index definitions/options, and extensions. It reports Alembic revisions separately. It refuses non-PostgreSQL, same-database, or non-`_disposable` targets, uses read-only transactions, and never loads `.env`.

For an unversioned existing schema, first create a fresh reference with Alembic upgrade head. Create the candidate using the currently supported application bootstrap (`Base.metadata.create_all` plus startup schema checks) on a second disposable database, and seed representative legacy records. Compare schemas against the fresh reference; table-name equality is insufficient. The current `create_all()` schema already contains columns and tables introduced by descendant revisions, so **do not stamp it at the base revision and replay descendants**. If the complete schema is identical, preserve the comparison report and stamp the candidate at the verified current head (`93b7e4c18a62`) without running an upgrade. If it differs in any way, stop and prepare a reviewed, forward-only reconciliation migration; do not stamp. Verify the recorded head and rerun comparison after adoption. Adoption is a per-database operation requiring an operator-reviewed comparison report and backup.

If a database already has a valid Alembic revision, do not stamp it. Inspect its recorded revision and use the normal forward upgrade after comparing its schema to the state expected at that revision.

## Legacy match preservation

The match-result migration is additive. It preserves `compatibility_score`, records old rows as `legacy`, and leaves model fields null. The representative legacy score-85 migration check performed on `raahi_test` passed in Phase 3A. Repeat it on a disposable database as part of the full Phase 3B validation.

## Validation state for this run

The implementation and comparison procedure are prepared, but fresh and simulated-existing PostgreSQL database demonstrations are pending. The only configured PostgreSQL role reports `CREATEDB=false`, no local PostgreSQL/Docker provisioning tools are installed, and no disposable database URLs have been supplied. No application database was connected to or modified. Do not stamp or migrate an application database based on this unrun procedure.
