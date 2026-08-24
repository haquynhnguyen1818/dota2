"""Fetch per-hero win rate by game-duration bucket from Stratz and load it into Postgres.

Backs the post-draft coach's power curve (docs/coaching_plan.md, Phase A1).

Deliberately a separate table from `stratz_hero_win_week` rather than filling
in that table's unused `duration_minute` column: `compute_hero_matchup_advantage.py`
picks the latest 2 weeks with `ROW_NUMBER() ... <= 2`, which is only correct
while there is exactly one row per hero-week. Adding duration rows there would
silently make it read two duration buckets of a single week instead.

Note `duration_bucket` is Stratz's `durationMinute`, which is a bucket *index*
(0-14), not a minute value -- renamed here so the column can't be mistaken for
minutes. Buckets are ~5 minutes wide; see docs/progress.md for the confirmed
mapping.
"""
from typing import Any

import psycopg
import requests

from app.config import creds_opendota, creds_stratzapi

STRATZ_URL = "https://api.stratz.com/graphql"

HEADERS = {
    "Authorization": f"Bearer {creds_stratzapi['token']}",
    "User-Agent": "STRATZ_API",
}

# `take` counts weeks, not rows -- 2000 fetches every week Stratz retains.
# All weeks are stored raw; consumers roll up to the latest 2 at query time,
# same convention as stratz_hero_win_week.
TAKE_WEEKS = 2000

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
    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode=creds_opendota.get("sslmode", "require"),
    ) as conn:
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
        f"into '{creds_opendota['db']}'."
    )


if __name__ == "__main__":
    main()
