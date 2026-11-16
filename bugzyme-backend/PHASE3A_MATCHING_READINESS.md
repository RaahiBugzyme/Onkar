# Phase 3A — matching persistence and migration readiness

## Alembic baseline investigation

The revisions form one linear chain:

`1d5280e25742 → 6a4f2b8c91de → 7c2f4a91d6b3 → 3d9e71b4c2a6 → 8f2c1a6b4d90 → a41d9e7c2b60 → c73e51a2b640 → ba28df14c601 → d9f4b2c81a67 → e12f3a4b5c6d → f62a9c31e7b4 → 93b7e4c18a62`

The first revision, `1d5280e25742_add_indexes.py`, is a root revision and unconditionally creates `ix_chats_user1_id`, `ix_chats_user2_id`, `ix_messages_chat_id`, and `ix_messages_sender_id`. It assumes `chats` and `messages` already exist and the indexes are absent. Raahi’s app startup calls `Base.metadata.create_all`, which creates these tables and indexes on a blank database. The message indexes duplicate the exact names already present; the chat indexes duplicate the same columns under the existing names `ix_chats_user1` and `ix_chats_user2`. Replaying Alembic fails on the exact duplicate `ix_messages_chat_id` (and would add redundant chat indexes before that point). Conversely, Alembic alone cannot bootstrap a blank database because no earlier revision creates the core `users`, `chats`, or `messages` tables.

The inspected `raahi_test` database has 17 application tables, these existing message indexes, and **no `alembic_version` table**. It is a metadata-created schema rather than a migration-tracked schema. A standard `alembic upgrade head` was attempted only against `raahi_test` and failed at the historical duplicate index. No historical migration file was changed. The application database was not inspected or modified.

Phase 2’s consent migration descends from `e12f3a4b5c6d`; the matching persistence migration descends from that consent revision. Both only add columns/backfill provenance and leave score values untouched. The Alembic graph now has one head, `93b7e4c18a62`.

### Safe reconciliation plan

1. Take a verified backup before any production reconciliation and inventory the production database’s tables, columns, constraints, and indexes read-only.
2. Compare that inventory with the intended schema at a named revision. Do not stamp merely because `create_all` completed; verify every intervening migration effect.
3. If production already matches the verified baseline, record that exact baseline in the migration ledger only after review. Then apply forward migrations and verify row counts and representative records.
4. If it does not match, write a forward-only reconciliation migration with existence checks for each missing table/index/column. Keep it additive; do not drop, truncate, or rewrite user or match data.
5. For fresh databases, choose one bootstrap path: either create the complete baseline through an explicit baseline migration or run metadata bootstrap once and stamp that verified baseline. Make the first index migration tolerant of already-present indexes before documenting a mixed bootstrap path.
6. Prove both paths against disposable empty and representative existing databases before touching production. Keep application startup and future Alembic upgrades on one documented schema authority.

This is a proposal only. No production stamping or historical migration edits were performed.

## Match persistence

`matches.compatibility_score` remains the legacy integer and retains historical values such as 85. New nullable fields hold raw compatibility, confidence, adjusted score, model version, eligibility status/reason, explanation JSON, component JSON, provenance, and calculation time. Existing records retain their score and receive `prediction_provenance='legacy'`; the genuine model fields remain null.

The adapter persistence method calls the original `CompatibilityModel` after its consent, age, verification, and block gates. It records each returned value in its own field and does not overwrite `compatibility_score`. The live swipe endpoint, feed, match list, and match detail do not call this method.

## Remaining score paths to change during activation

| Path | Current behavior | Required activation change |
|---|---|---|
| `GET /api/v1/feed` | Era points (30/10), vibe points (30), and placeholder bio points (40); caps at 100 and sorts by this fabricated score. | Replace with eligibility-gated Dating ML prediction, preserve ineligible/unknown state, persist result, and sort only according to approved model fields. |
| Mutual swipe match creation | Explicitly writes `compatibility_score=85`; Match column also defaults to 85. | Persist the real model payload through the new fields. Keep the old integer field legacy-only and never backfill it as ML. |
| Swipe match response | Returns `match.compatibility_score`, so new matches return 85. | Return provenance and genuine nullable score fields; avoid presenting a legacy value as a prediction. |
| Match listing | Returns stored `compatibility_score` (commonly 85). | Return stored model fields and provenance separately; do not synthesize scores for legacy rows. |
| Match detail | Returns stored `compatibility_score` (commonly 85). | Same provenance-aware response as listing. |
| `ProfileCard` | Displays any truthy `compatibility_score` with a percent sign. Feed scores appear as percentages. | Render a genuine score only when provenance/model metadata identifies one; display unknown/ineligible distinctly. |
| `MatchOverlay` | Requires a numeric score in its TypeScript shape but currently does not render it. | Use nullable provenance-aware fields if the overlay later presents a score. |

No scoring or matching display path was changed in Phase 3A.
