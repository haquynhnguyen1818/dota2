"""Load hero role assignments from hero_role.csv into Postgres."""
import csv
from pathlib import Path

import psycopg

from app.config import creds_opendota

HERO_ROLE_CSV = Path(__file__).resolve().parents[3] / "data" / "hero_role.csv"

CREATE_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS roles_csv_import (
    role_id SERIAL PRIMARY KEY,
    role_name TEXT UNIQUE NOT NULL
)
"""

CREATE_HERO_ROLES_TABLE = """
CREATE TABLE IF NOT EXISTS hero_roles_csv_import (
    hero_id INT NOT NULL REFERENCES heroes(id) ON DELETE CASCADE,
    role_id INT NOT NULL REFERENCES roles_csv_import(role_id) ON DELETE CASCADE,
    PRIMARY KEY (hero_id, role_id)
)
"""


def main() -> None:
    with open(HERO_ROLE_CSV, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    role_names = sorted({row["Role"] for row in rows})
    pairs = sorted({(int(row["hero_id"]), row["Role"]) for row in rows})

    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode=creds_opendota.get("sslmode", "require"),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_ROLES_TABLE)
            cur.execute(CREATE_HERO_ROLES_TABLE)
            cur.execute("TRUNCATE hero_roles_csv_import")

            cur.executemany(
                "INSERT INTO roles_csv_import (role_name) VALUES (%s) ON CONFLICT (role_name) DO NOTHING",
                [(r,) for r in role_names],
            )
            cur.execute("SELECT role_name, role_id FROM roles_csv_import")
            role_id_by_name = dict(cur.fetchall())

            cur.executemany(
                "INSERT INTO hero_roles_csv_import (hero_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                [(hero_id, role_id_by_name[role]) for hero_id, role in pairs],
            )
            cur.execute("SELECT count(*) FROM hero_roles_csv_import")
            count = cur.fetchone()[0]
        conn.commit()

        print(f"Loaded {count} hero_roles_csv_import rows.")


if __name__ == "__main__":
    main()
