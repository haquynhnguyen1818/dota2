"""Load hero role assignments from the hero-role Google Sheet into Postgres."""
import csv
import io

import psycopg
import requests

from app.credentials import db_kwargs

# The hand-curated hero -> role sheet, readable by anyone with the link.
# `export?format=csv` serves its first tab. This replaced `data/hero_role.csv`,
# which was deleted so there is only one source to edit.
HERO_ROLE_SHEET_CSV = (
    "https://docs.google.com/spreadsheets/d/"
    "1OH3IBksFy66GDTGgyuh9U0CsjbI-98DTns1lZYY1Hmw/export?format=csv"
)

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
    resp = requests.get(HERO_ROLE_SHEET_CSV, timeout=30)
    resp.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))

    role_names = sorted({row["Role"] for row in rows})
    pairs = sorted({(int(row["hero_id"]), row["Role"]) for row in rows})

    with psycopg.connect(**db_kwargs()) as conn:
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
