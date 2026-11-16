# Dating ML result storage proposal — not applied

No schema change is made in Phase 1. Proposed additive migration:

- Add nullable `compatibility_score` (numeric), `confidence_score` (numeric), and `adjusted_score` (numeric) to `matches`.
- Add nullable `model_version` (string), `eligibility_status` (boolean), `eligibility_reason` (text), `explanation_json` (JSON/text), and `components_json` (JSON/text).
- Keep legacy `compatibility_score` values distinguishable: add a result provenance/source field or backfill legacy rows to `legacy` with eligibility unknown. Never label old default-85 rows as ML results.
- Preserve nullable fields for ineligible pairs and unknown inputs. Do not synthesize score values.
- Add range constraints only after confirming the engine's exact score bounds and numeric precision; test upgrade/downgrade against a disposable database.

Review and approval are required before implementing or applying this proposal.
