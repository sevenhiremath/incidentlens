# PostgreSQL and Docker

The quickest local run uses SQLite. The Compose file runs PostgreSQL, the API, Streamlit, and the Flask demo in separate containers. This is a local setup, not a public deployment configuration.

First create `.env`:

```text
uv run python scripts/setup_local.py
```

Then:

```text
docker compose build
docker compose up -d db
docker compose run --rm backend python manage.py migrate
docker compose run --rm backend python manage.py createuser
docker compose up -d backend dashboard demo
```

Open `http://localhost:8501`. Register **`http://demo:5055/health`**, because the monitor runs inside the Compose network. `127.0.0.1` inside that container refers to the container itself.

Start the single monitor:

```text
docker compose --profile monitoring up -d monitor
```

The demo control script can run on your host:

```text
uv run python scripts/demo_control.py down
uv run python scripts/demo_control.py healthy
```

For the scripted walkthrough, stop the continuous monitor and run
`uv run python scripts/demo_walkthrough.py --docker` on the host. This uses the
API through its local published port and runs each check inside the backend
container. CI uses this same flow with a disposable test account.

To stop the containers while keeping the database volume:

```text
docker compose --profile monitoring down
```

The published ports bind to the local machine. PostgreSQL has no published host port. The application containers use a non-root account. Before any public hosting, add HTTPS, review allowed hosts and monitor targets, and configure proper logging, backups, and token handling.

## Run checks against PostgreSQL

The GitHub Actions workflow creates a PostgreSQL service and sets `DATABASE_ENGINE=postgres`. It runs the same tests plus the PostgreSQL-only concurrency tests. You can do the same locally with an existing PostgreSQL instance by editing the `POSTGRES_*` values in `.env` and setting `DATABASE_ENGINE=postgres`. The test role needs permission to create a temporary test database; do not use a production database account.

See [the verification notes](demo.md) for what has actually been run. A configuration file by itself is not proof that a deployment was tested.
