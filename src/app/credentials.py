"""Credential resolution for everything that talks to Postgres or Stratz.

Environment first, `app.config` second. Production containers get env vars from
`infra/.env` via docker-compose; local dev has a gitignored `src/app/config.py`
and no env vars. Same code works in both without a branch at the call site.

This exists because ingestion could not run in production: only `api/db.py`
read the environment, so every loader hardcoded a gitignored import and was
stuck on the developer's machine. The weekly refresh job needs them all to run
inside the API container, which ships no `config.py`.

This module is the only place that knows the env var names.
"""
import os

try:
    from app.config import creds_opendota, creds_stratzapi
except ImportError:  # the production image ships no config.py
    creds_opendota, creds_stratzapi = {}, {}


def db_kwargs() -> dict[str, str]:
    """Keyword arguments for `psycopg.connect()`."""
    kwargs = {
        "host": os.environ.get("DB_HOST", creds_opendota.get("host", "")),
        "port": os.environ.get("DB_PORT", creds_opendota.get("port", "")),
        "user": os.environ.get("DB_USER", creds_opendota.get("user", "")),
        "password": os.environ.get("DB_PASSWORD", creds_opendota.get("pw", "")),
        "dbname": os.environ.get("DB_NAME", creds_opendota.get("db", "")),
        "sslmode": os.environ.get("DB_SSLMODE", creds_opendota.get("sslmode", "require")),
    }
    missing = [key for key in ("host", "user", "dbname") if not kwargs[key]]
    if missing:
        raise RuntimeError(
            f"Database not configured (missing {', '.join(missing)}): set "
            "DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME, or provide "
            "src/app/config.py for local dev."
        )
    return kwargs


def stratz_headers() -> dict[str, str]:
    """Auth headers for api.stratz.com. The User-Agent is required, not cosmetic."""
    token = os.environ.get("STRATZ_TOKEN") or creds_stratzapi.get("token", "")
    if not token:
        raise RuntimeError(
            "Stratz token not configured: set STRATZ_TOKEN, or provide "
            "src/app/config.py for local dev."
        )
    return {"Authorization": f"Bearer {token}", "User-Agent": "STRATZ_API"}
