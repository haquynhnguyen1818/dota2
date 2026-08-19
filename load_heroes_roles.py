import csv
import os
import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]

DDL = """
CREATE TABLE IF NOT EXISTS roles (
    role_id SERIAL PRIMARY KEY,
    role_name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS heroes (
    hero_id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS hero_roles (
    hero_id INT NOT NULL REFERENCES heroes(hero_id) ON DELETE CASCADE,
    role_id INT NOT NULL REFERENCES roles(role_id) ON DELETE CASCADE,
    PRIMARY KEY (hero_id, role_id)
);
"""

with open("hero_role.csv", newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

hero_names = sorted({row["Heroes"] for row in rows})
role_names = sorted({row["Role"] for row in rows})
pairs = sorted({(row["Heroes"], row["Role"]) for row in rows})

conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

cur.execute(DDL)

cur.executemany(
    "INSERT INTO roles (role_name) VALUES (%s) ON CONFLICT (role_name) DO NOTHING",
    [(r,) for r in role_names],
)
cur.executemany(
    "INSERT INTO heroes (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
    [(h,) for h in hero_names],
)

cur.execute("SELECT name, hero_id FROM heroes")
hero_id_by_name = dict(cur.fetchall())
cur.execute("SELECT role_name, role_id FROM roles")
role_id_by_name = dict(cur.fetchall())

cur.executemany(
    "INSERT INTO hero_roles (hero_id, role_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
    [(hero_id_by_name[h], role_id_by_name[r]) for h, r in pairs],
)

conn.commit()

cur.execute("SELECT count(*) FROM heroes")
print("heroes:", cur.fetchone()[0])
cur.execute("SELECT count(*) FROM roles")
print("roles:", cur.fetchone()[0])
cur.execute("SELECT count(*) FROM hero_roles")
print("hero_roles:", cur.fetchone()[0])

cur.close()
conn.close()
