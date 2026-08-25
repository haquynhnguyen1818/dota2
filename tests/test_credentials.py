"""Tests for credential resolution (app/credentials.py).

The production containers ship no `config.py` and set env vars instead; local
dev is the reverse. Both paths have to work, and the precedence between them
has to be the right way round -- getting it backwards would silently point the
weekly refresh job at the developer's machine.
"""
import pytest

from app import credentials
from app.credentials import coach_pin, db_kwargs, stratz_headers

DB_VARS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME", "DB_SSLMODE")

CONFIG = {
    "host": "cfg-host", "port": "5432", "user": "cfg-user",
    "pw": "cfg-pw", "db": "cfg-db", "sslmode": "disable",
}


@pytest.fixture
def no_env(monkeypatch):
    """A clean environment, so config.py is the only source."""
    for var in (*DB_VARS, "STRATZ_TOKEN", "COACH_PIN"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def from_config(monkeypatch, no_env):
    monkeypatch.setattr(credentials, "creds_opendota", CONFIG)


@pytest.fixture
def no_config(monkeypatch):
    monkeypatch.setattr(credentials, "creds_opendota", {})


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

def test_config_is_used_when_the_environment_is_empty(from_config):
    assert db_kwargs() == {
        "host": "cfg-host", "port": "5432", "user": "cfg-user",
        "password": "cfg-pw", "dbname": "cfg-db", "sslmode": "disable",
    }


def test_environment_wins_over_config(from_config, monkeypatch):
    monkeypatch.setenv("DB_HOST", "db")
    monkeypatch.setenv("DB_NAME", "prod")
    resolved = db_kwargs()
    assert resolved["host"] == "db" and resolved["dbname"] == "prod"
    # Unset vars still fall back rather than blanking out.
    assert resolved["user"] == "cfg-user"


def test_environment_alone_is_enough(no_config, monkeypatch):
    for var in DB_VARS:
        monkeypatch.setenv(var, "x")
    assert db_kwargs()["host"] == "x"


def test_sslmode_defaults_to_require(no_config, monkeypatch):
    # A missing sslmode must not silently downgrade a hosted connection.
    for var in ("DB_HOST", "DB_USER", "DB_NAME"):
        monkeypatch.setenv(var, "x")
    monkeypatch.delenv("DB_SSLMODE", raising=False)
    assert db_kwargs()["sslmode"] == "require"


def test_missing_database_config_names_what_is_missing(no_config, no_env):
    with pytest.raises(RuntimeError, match="host, user, dbname"):
        db_kwargs()


def test_a_password_is_not_required(no_config, monkeypatch, no_env):
    # Trust auth and .pgpass are both legitimate; only host/user/dbname are checked.
    for var in ("DB_HOST", "DB_USER", "DB_NAME"):
        monkeypatch.setenv(var, "x")
    assert db_kwargs()["password"] == ""


# --------------------------------------------------------------------------
# Stratz
# --------------------------------------------------------------------------

def test_stratz_headers_come_from_the_environment(no_config, monkeypatch):
    monkeypatch.setenv("STRATZ_TOKEN", "env-token")
    assert stratz_headers() == {
        "Authorization": "Bearer env-token",
        "User-Agent": "STRATZ_API",
    }


def test_stratz_never_falls_back_to_config(from_config):
    # Unlike the database, config.py must NOT satisfy Stratz. The token is
    # bound to one IP and belongs to the Droplet; a laptop picking it up from
    # config.py would re-bind it and break the next weekly refresh, days later
    # and silently. Failing loudly here is the whole point.
    with pytest.raises(RuntimeError, match="bound to one IP"):
        stratz_headers()


def test_an_empty_stratz_token_raises(from_config, monkeypatch):
    # Compose writes STRATZ_TOKEN="" when the var is absent from .env, so an
    # empty string must be treated as missing rather than as a real token.
    monkeypatch.setenv("STRATZ_TOKEN", "")
    with pytest.raises(RuntimeError):
        stratz_headers()


def test_missing_stratz_token_names_the_way_out(no_config, no_env):
    with pytest.raises(RuntimeError, match="docker compose"):
        stratz_headers()


# --------------------------------------------------------------------------
# Coach PIN
# --------------------------------------------------------------------------

def test_coach_pin_comes_from_the_environment(no_env, monkeypatch):
    monkeypatch.setenv("COACH_PIN", "1234")
    assert coach_pin() == "1234"


def test_coach_pin_falls_back_to_config(no_env, monkeypatch):
    # Unlike Stratz, the PIN has no IP-binding hazard, so config.py works here
    # the same way it does for the database.
    monkeypatch.setattr(credentials, "_cfg_coach_pin", "cfg-pin")
    assert coach_pin() == "cfg-pin"


def test_coach_pin_environment_wins_over_config(no_env, monkeypatch):
    monkeypatch.setattr(credentials, "_cfg_coach_pin", "cfg-pin")
    monkeypatch.setenv("COACH_PIN", "env-pin")
    assert coach_pin() == "env-pin"


def test_missing_coach_pin_is_an_empty_string_not_an_error(no_env, monkeypatch):
    # The router, not this module, decides an unconfigured PIN is fatal --
    # coach_pin() just reports what it found.
    monkeypatch.setattr(credentials, "_cfg_coach_pin", "")
    assert coach_pin() == ""
