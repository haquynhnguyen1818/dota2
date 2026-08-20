"""Shared DB connection dependency for the API layer."""
from collections.abc import Iterator

import psycopg

from app.config import creds_opendota


def get_conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode="require",
    ) as conn:
        yield conn
