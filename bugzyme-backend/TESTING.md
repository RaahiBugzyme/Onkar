# Backend test database and verification retention

## Isolated PostgreSQL test database

Automated pytest runs require a dedicated PostgreSQL database. Set
`TEST_DATABASE_URL` in the process environment or copy `.env.test.example` to
`.env.test` and provide credentials for a test-only database. The database name
must start with `test_` or end with `_test`; `TEST_DATABASE_URL` must not target
the same host, port, and database as the application's `DATABASE_URL`.

The pytest configuration validates the URL before importing application
modules, replaces `DATABASE_URL` with the validated test URL, and reports only
the selected database name. It serializes pytest runs that share the test
database and refuses pytest-xdist. Sessions are closed (rolling back any open
transaction) and committed rows are truncated from the guarded test database
after each test. Schema creation remains in the test database so it can be
reused. The suite never creates, drops, truncates, or resets the application
database.

Provision the test database separately, for example `raahi_test`, and never
point `TEST_DATABASE_URL` at the application database. Missing or unsafe test
configuration stops pytest during startup. The safety checks also reject
cleanup if the active connection no longer resolves to the validated test DB.

Run tests from this directory:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Daily verification retention

FastAPI workers do not schedule retention work. Install the systemd service and
timer under `deployment/systemd/` on the backend host, adapting the service
user, working directory, virtual-environment path, and environment-file path
to that deployment. The environment file must contain the backend's normal
database and secret configuration. Enable the timer with:

```sh
sudo systemctl enable --now raahi-verification-retention.timer
```

`Persistent=true` runs a missed daily invocation after the host returns. The
service retries failures, exits nonzero on errors, and logs details without
printing credentials. A PostgreSQL session advisory lock prevents overlapping
timer invocations across processes or hosts sharing the database. The 30-day
policy remains in force; requests are expired only after their retention age,
and active `pending` requests are excluded from evidence deletion.
