"""Load hand-authored hero capability tags from hero_tags.csv into Postgres.

Post-draft coach, Phase E3/E4 (docs/coaching_plan.md). Backs the coach's
`my_comp`/`their_comp` counts — "do we have lockdown, do they have a save".

The CSV is the source of truth and is maintained by hand, same as
`hero_role.csv`. Deriving it was tried and abandoned: Stratz's modifier flags
turned out to be sparsely populated (`isBreak` matches one modifier in the
whole constants set) and OpenDota's role tags are far too coarse. See the E3
section of coaching_plan.md for what each tag means.

Every cell is an explicit 0 or 1 — a blank would be a mistake, so it's rejected
rather than silently read as false.
"""
import csv
from pathlib import Path

import psycopg

from app.credentials import db_kwargs

HERO_TAGS_CSV = Path(__file__).resolve().parents[3] / "data" / "hero_tags.csv"

TAGS = ["lockdown", "save", "dispel", "waveclear", "tower_dmg",
        "silence", "break", "cheap_ult", "illusion", "summons"]

# "break" is a reserved word in some SQL contexts, so every tag column is quoted.
CREATE_HERO_TAGS_TABLE = f"""
CREATE TABLE IF NOT EXISTS hero_tags (
    hero_id INT PRIMARY KEY REFERENCES heroes(id) ON DELETE CASCADE,
    {", ".join(f'"{t}" BOOLEAN NOT NULL' for t in TAGS)}
)
"""

UPSERT_HERO_TAGS = f"""
INSERT INTO hero_tags (hero_id, {", ".join(f'"{t}"' for t in TAGS)})
VALUES (%s, {", ".join(["%s"] * len(TAGS))})
ON CONFLICT (hero_id) DO UPDATE SET
    {", ".join(f'"{t}" = EXCLUDED."{t}"' for t in TAGS)}
"""


def read_rows() -> list[tuple]:
    with open(HERO_TAGS_CSV, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    out = []
    for row in rows:
        values = []
        for tag in TAGS:
            raw = (row.get(tag) or "").strip()
            if raw not in ("0", "1"):
                raise ValueError(
                    f"{HERO_TAGS_CSV.name}: {row['Heroes']} has {raw!r} for '{tag}'; "
                    "every cell must be an explicit 0 or 1"
                )
            values.append(raw == "1")
        out.append((int(row["hero_id"]), *values))
    return out


def main() -> None:
    rows = read_rows()

    with psycopg.connect(**db_kwargs()) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_HERO_TAGS_TABLE)
            cur.executemany(UPSERT_HERO_TAGS, rows)
            cur.execute("SELECT count(*) FROM hero_tags")
            count = cur.fetchone()[0]
        conn.commit()

    print(f"Loaded {len(rows)} rows from {HERO_TAGS_CSV.name}; hero_tags now has {count}.")


if __name__ == "__main__":
    main()
