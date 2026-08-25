"""Fetch hero-vs-hero matchup data from the Stratz GraphQL API and load it into Postgres."""
from collections import defaultdict
from typing import Any

import psycopg
import requests

from app.credentials import db_kwargs, stratz_headers

STRATZ_URL = "https://api.stratz.com/graphql"

RECENT_WEEKS = 2

MATCHUP_QUERY = """
query ($heroIds: [Short], $take: Int, $week: Long) {
  heroStats {
    matchUp(heroIds: $heroIds, take: $take, week: $week) {
      heroId
      vs {
        heroId2
        matchCount
        winCount
      }
    }
  }
}
"""

CREATE_STRATZ_MATCHUPS_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_matchups (
    hero_id INTEGER REFERENCES heroes(id),
    vs_hero_id INTEGER REFERENCES heroes(id),
    games_played BIGINT,
    wins BIGINT,
    PRIMARY KEY (hero_id, vs_hero_id)
)
"""

UPSERT_STRATZ_MATCHUP = """
INSERT INTO stratz_hero_matchups (hero_id, vs_hero_id, games_played, wins)
VALUES (%(hero_id)s, %(vs_hero_id)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, vs_hero_id) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""


# Batched for the same reason as load_stratz_synergy.py: Stratz truncates large
# responses mid-stream. All 127 heroes returns ~787KB here -- it has not failed
# yet, but that is uncomfortably close to the ~1MB where the sibling synergy
# query fails half the time. 32 heroes is ~200KB. Each requested hero returns
# all 126 opponents regardless of batch size, so nothing is lost.
HERO_BATCH = 32


def fetch_hero_matchups(hero_ids: list[int], week: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(hero_ids), HERO_BATCH):
        rows += _fetch_matchup_batch(hero_ids[start : start + HERO_BATCH], week)
    return rows


def _fetch_matchup_batch(hero_ids: list[int], week: int) -> list[dict[str, Any]]:
    headers = stratz_headers()
    response = requests.post(
        STRATZ_URL,
        json={"query": MATCHUP_QUERY, "variables": {"heroIds": hero_ids, "take": 200, "week": week}},
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])

    rows = []
    for hero in data["data"]["heroStats"]["matchUp"]:
        for vs in hero["vs"]:
            rows.append(
                {
                    "hero_id": hero["heroId"],
                    "vs_hero_id": vs["heroId2"],
                    "games_played": vs["matchCount"],
                    "wins": vs["winCount"],
                }
            )
    return rows


def main() -> None:
    with psycopg.connect(**db_kwargs()) as conn:
        hero_ids = [r[0] for r in conn.execute("SELECT id FROM heroes ORDER BY id").fetchall()]
        weeks = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT week FROM stratz_hero_win_week ORDER BY week DESC LIMIT {RECENT_WEEKS}"
            ).fetchall()
        ]

        totals: dict[tuple[int, int], dict[str, int]] = defaultdict(lambda: {"games_played": 0, "wins": 0})
        for week in weeks:
            for row in fetch_hero_matchups(hero_ids, week):
                key = (row["hero_id"], row["vs_hero_id"])
                totals[key]["games_played"] += row["games_played"]
                totals[key]["wins"] += row["wins"]

        matchup_rows = [
            {"hero_id": hero_id, "vs_hero_id": vs_hero_id, **stats}
            for (hero_id, vs_hero_id), stats in totals.items()
        ]

        with conn.cursor() as cur:
            cur.execute(CREATE_STRATZ_MATCHUPS_TABLE)
            cur.executemany(UPSERT_STRATZ_MATCHUP, matchup_rows)
        conn.commit()

    print(
        f"Loaded {len(matchup_rows)} stratz_hero_matchups rows "
        f"(summed over weeks {weeks}) into '{db_kwargs()['dbname']}'."
    )


if __name__ == "__main__":
    main()
