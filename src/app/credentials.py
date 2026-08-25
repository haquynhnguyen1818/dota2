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
    from app.config import creds_opendota
except ImportError:  # the production image ships no config.py
    creds_opendota = {}

try:
    from app.config import coach_pin as _cfg_coach_pin
except ImportError:  # not set locally, or no config.py at all
    _cfg_coach_pin = ""


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
    """Auth headers for api.stratz.com. The User-Agent is required, not cosmetic.

    **Environment only -- deliberately no config.py fallback**, unlike the
    database. Stratz binds a token to one IP address: a second caller gets
    `403 You cannot use different IP Addresses when using the API` and the whole
    token starts refusing, not just the new caller. The Droplet owns the token
    because it owns the weekly refresh cron, so a Stratz loader run from a
    laptop must fail loudly here rather than silently re-bind the token and
    break the next cron run days later.

    The container gets STRATZ_TOKEN from infra/.env. Setting it in a local shell
    still works, which is the point: that is a deliberate act, not an accident.
    """
    token = os.environ.get("STRATZ_TOKEN", "")
    if not token:
        raise RuntimeError(
            "STRATZ_TOKEN is not set. The Stratz token is bound to one IP and "
            "belongs to the Droplet -- running this locally would re-bind it and "
            "break the weekly refresh. Run the loader there instead:\n"
            "  docker compose -f infra/docker-compose.yml run --rm -T api "
            "python -m app.ingestion.<loader>"
        )
    return {"Authorization": f"Bearer {token}", "User-Agent": "STRATZ_API"}


def coach_pin() -> str:
    """The master PIN that unlocks extra `/coach` calls once the rate limit hits.

    Same env-first-then-config.py resolution as the database -- unlike Stratz,
    there's no IP binding here, so testing the unlock flow locally is fine.
    Empty string means "not configured", which the caller must reject rather
    than let an unset PIN match an empty submitted PIN.
    """
    return os.environ.get("COACH_PIN", _cfg_coach_pin)
