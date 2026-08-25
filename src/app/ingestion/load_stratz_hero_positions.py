"""Fetch per-hero lane/position distribution from Stratz and load it into Postgres.

Backs the post-draft coach's `predicted_lane` (docs/coaching_plan.md, Phase E1).

Source is `heroStats.stats(groupByPosition: true)`, which is the **only** place
position data exists — positions have to be inferred from a parsed match, so
this endpoint covers roughly a third of the matches `winWeek` does. That subset
is fine for a *distribution* question (nothing links whether a match got parsed
to which position a hero was played in), but don't compare its absolute counts
against `stratz_hero_win_week` or `stratz_hero_duration_wr`.

Per user decision this is the coach's only position source; `hero_role.csv`
stays scoped to the pick-suggestion feature and is not consulted here.

Note `stats` echoes `week` as a week *index* (e.g. 2954) while every other
table in this schema uses the Unix timestamp Stratz's `winWeek` returns
(1786579200 = 604800 * 2954, the same week). The requested timestamp is what
gets stored, so this table joins cleanly with the rest.
"""
from collections import defaultdict
from typing import Any

import psycopg
import requests

from app.credentials import db_kwargs, stratz_headers

STRATZ_URL = "https://api.stratz.com/graphql"

HEADERS = stratz_headers()

RECENT_WEEKS = 2

POSITION_QUERY = """
query ($heroIds: [Short], $week: Long) {
  heroStats {
    stats(heroIds: $heroIds, groupByPosition: true, week: $week) {
      heroId
      position
      matchCount
      winCount
    }
  }
}
"""

CREATE_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_positions (
    hero_id INTEGER REFERENCES stratz_heroes(id),
    week BIGINT,
    position TEXT,
    games_played BIGINT,
    wins BIGINT,
    PRIMARY KEY (hero_id, week, position)
)
"""

UPSERT_POSITION = """
INSERT INTO stratz_hero_positions (hero_id, week, position, games_played, wins)
VALUES (%(hero_id)s, %(week)s, %(position)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, week, position) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""


def fetch_positions(hero_ids: list[int], week: int) -> list[dict[str, Any]]:
    response = requests.post(
        STRATZ_URL,
        json={"query": POSITION_QUERY, "variables": {"heroIds": hero_ids, "week": week}},
        headers=HEADERS,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])

    return [
        {
            "hero_id": r["heroId"],
            "week": week,  # store the requested timestamp, not stats' week index
            "position": r["position"],
            "games_played": r["matchCount"],
            "wins": r["winCount"],
        }
        for r in data["data"]["heroStats"]["stats"]
    ]


def main() -> None:
    with psycopg.connect(**db_kwargs()) as conn:
        hero_ids = [r[0] for r in conn.execute("SELECT id FROM stratz_heroes ORDER BY id").fetchall()]
        weeks = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT week FROM stratz_hero_win_week ORDER BY week DESC LIMIT {RECENT_WEEKS}"
            ).fetchall()
        ]

        rows: list[dict[str, Any]] = []
        for week in weeks:
            rows.extend(fetch_positions(hero_ids, week))

        with conn.cursor() as cur:
            cur.execute(CREATE_POSITIONS_TABLE)
            cur.executemany(UPSERT_POSITION, rows)
        conn.commit()

    by_hero: dict[int, int] = defaultdict(int)
    for r in rows:
        by_hero[r["hero_id"]] += r["games_played"]
    print(
        f"Loaded {len(rows)} stratz_hero_positions rows "
        f"({len(by_hero)} heroes over weeks {weeks}) into '{db_kwargs()['dbname']}'."
    )


if __name__ == "__main__":
    main()
