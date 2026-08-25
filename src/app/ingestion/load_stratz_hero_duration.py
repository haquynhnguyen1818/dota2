"""Fetch per-hero win rate by game-duration bucket from Stratz and load it into Postgres.

Backs the post-draft coach's power curve (docs/coaching_plan.md, Phase A1).

Deliberately a separate table from `stratz_hero_win_week` rather than filling in
that table's unused `duration_minute` column. Writing bucket rows there would
collide bucket 0 with the existing per-week total row (same PK) and leave one
table meaning two different things.

Historical note: this split was originally motivated by
`compute_hero_matchup_advantage.py` reading that table with
`ROW_NUMBER() ... <= 2`, which only works while there is one row per hero-week.
Commit 01529a2 rebased `hero_wr` onto `stratz_hero_matchups`, so that specific
hazard is gone — but the equivalent trap now lives on *this* table, which has 14
rows per hero-week. See `engine/draft_context.py`'s `load_bucket_stats`.

Note `duration_bucket` is Stratz's `durationMinute`, which is a bucket *index*
(0-14), not a minute value -- renamed here so the column can't be mistaken for
minutes. Buckets are ~5 minutes wide; see docs/progress.md for the confirmed
mapping.
"""
from typing import Any

import psycopg
import requests

from app.credentials import db_kwargs, stratz_headers

STRATZ_URL = "https://api.stratz.com/graphql"

HEADERS = stratz_headers()

# `take` counts weeks, not rows, and this is deliberately small.
#
# This table holds 14 rows per hero-week, so asking for every week Stratz
# retains (`take: 2000`, which is what this used to do) returns ~2.8MB gzipped
# -- and Stratz truncates it mid-stream, raising ChunkedEncodingError. Measured
# from the Droplet: all weeks cut off at 1,862,679 bytes, while 2 weeks
# returned 305,316 bytes cleanly. Four weeks is ~600KB, well clear of the
# cutoff, and still repairs a month of missed refresh runs.
#
# Nothing is lost by asking for less: rows upsert on
# (hero_id, week, duration_bucket), so weeks already loaded stay put, and
# consumers only ever roll up to the latest 2 weeks at query time. Use a larger
# value only for a one-off historical backfill, and expect to page it.
TAKE_WEEKS = 4

DURATION_QUERY = """
query ($heroIds: [Short], $take: Int) {
  heroStats {
    winWeek(heroIds: $heroIds, take: $take, groupBy: HERO_ID_DURATION_MINUTES) {
      heroId
      week
      durationMinute
      matchCount
      winCount
    }
  }
}
"""

CREATE_DURATION_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_duration_wr (
    hero_id INTEGER REFERENCES stratz_heroes(id),
    week BIGINT,
    duration_bucket INTEGER,
    games_played INTEGER,
    wins INTEGER,
    PRIMARY KEY (hero_id, week, duration_bucket)
)
"""

UPSERT_DURATION_WR = """
INSERT INTO stratz_hero_duration_wr (hero_id, week, duration_bucket, games_played, wins)
VALUES (%(hero_id)s, %(week)s, %(duration_bucket)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, week, duration_bucket) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""


def fetch_duration_wr(hero_ids: list[int]) -> list[dict[str, Any]]:
    response = requests.post(
        STRATZ_URL,
        json={"query": DURATION_QUERY, "variables": {"heroIds": hero_ids, "take": TAKE_WEEKS}},
        headers=HEADERS,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])

    return [
        {
            "hero_id": r["heroId"],
            "week": r["week"],
            "duration_bucket": r["durationMinute"],
            "games_played": r["matchCount"],
            "wins": r["winCount"],
        }
        for r in data["data"]["heroStats"]["winWeek"]
    ]


def main() -> None:
    with psycopg.connect(**db_kwargs()) as conn:
        hero_ids = [r[0] for r in conn.execute("SELECT id FROM stratz_heroes ORDER BY id").fetchall()]
        rows = fetch_duration_wr(hero_ids)

        with conn.cursor() as cur:
            cur.execute(CREATE_DURATION_TABLE)
            cur.executemany(UPSERT_DURATION_WR, rows)
        conn.commit()

    weeks = len({r["week"] for r in rows})
    print(
        f"Loaded {len(rows)} stratz_hero_duration_wr rows "
        f"({len({r['hero_id'] for r in rows})} heroes x {weeks} weeks) "
        f"into '{db_kwargs()['dbname']}'."
    )


if __name__ == "__main__":
    main()
