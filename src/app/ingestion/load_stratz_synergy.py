"""Fetch hero duo synergy data (heroes played on the same team) from the Stratz GraphQL API and load it into Postgres."""
from collections import defaultdict
from typing import Any

import psycopg
import requests

from app.credentials import db_kwargs, stratz_headers

STRATZ_URL = "https://api.stratz.com/graphql"

RECENT_WEEKS = 2

SYNERGY_QUERY = """
query ($heroIds: [Short], $take: Int, $week: Long) {
  heroStats {
    matchUp(heroIds: $heroIds, take: $take, week: $week) {
      heroId
      with {
        heroId2
        matchCount
        winCount
        synergy
      }
    }
  }
}
"""

CREATE_STRATZ_SYNERGY_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_synergy (
    hero_id INTEGER REFERENCES heroes(id),
    with_hero_id INTEGER REFERENCES heroes(id),
    games_played BIGINT,
    wins BIGINT,
    synergy NUMERIC,
    PRIMARY KEY (hero_id, with_hero_id)
)
"""

UPSERT_STRATZ_SYNERGY = """
INSERT INTO stratz_hero_synergy (hero_id, with_hero_id, games_played, wins, synergy)
VALUES (%(hero_id)s, %(with_hero_id)s, %(games_played)s, %(wins)s, %(synergy)s)
ON CONFLICT (hero_id, with_hero_id) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins,
    synergy = EXCLUDED.synergy
"""


# Stratz truncates large responses mid-stream (see docs/progress.md). All 127
# heroes in one request returns ~1.05MB and fails roughly half the time --
# measured 3 failures in 6 attempts, buffered and streamed alike. 32 heroes is
# ~265KB, with comfortable margin.
#
# Batching costs nothing: each requested hero comes back with all 126 partners
# regardless of how many heroes are asked for, verified against the live API.
# So the batches never need to be cross-joined, and 4 requests per week stay far
# inside the 8/second limit.
HERO_BATCH = 32


def fetch_hero_synergy(hero_ids: list[int], week: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(hero_ids), HERO_BATCH):
        rows += _fetch_synergy_batch(hero_ids[start : start + HERO_BATCH], week)
    return rows


def _fetch_synergy_batch(hero_ids: list[int], week: int) -> list[dict[str, Any]]:
    headers = stratz_headers()
    response = requests.post(
        STRATZ_URL,
        json={"query": SYNERGY_QUERY, "variables": {"heroIds": hero_ids, "take": 200, "week": week}},
        headers=headers,
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])

    rows = []
    for hero in data["data"]["heroStats"]["matchUp"]:
        for with_hero in hero["with"]:
            rows.append(
                {
                    "hero_id": hero["heroId"],
                    "with_hero_id": with_hero["heroId2"],
                    "games_played": with_hero["matchCount"],
                    "wins": with_hero["winCount"],
                    "synergy": with_hero["synergy"],
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

        totals: dict[tuple[int, int], dict[str, float]] = defaultdict(
            lambda: {"games_played": 0, "wins": 0, "synergy_weighted": 0.0}
        )
        for week in weeks:
            for row in fetch_hero_synergy(hero_ids, week):
                key = (row["hero_id"], row["with_hero_id"])
                totals[key]["games_played"] += row["games_played"]
                totals[key]["wins"] += row["wins"]
                totals[key]["synergy_weighted"] += row["synergy"] * row["games_played"]

        synergy_rows = [
            {
                "hero_id": hero_id,
                "with_hero_id": with_hero_id,
                "games_played": stats["games_played"],
                "wins": stats["wins"],
                "synergy": stats["synergy_weighted"] / stats["games_played"] if stats["games_played"] else None,
            }
            for (hero_id, with_hero_id), stats in totals.items()
        ]

        with conn.cursor() as cur:
            cur.execute(CREATE_STRATZ_SYNERGY_TABLE)
            cur.executemany(UPSERT_STRATZ_SYNERGY, synergy_rows)
        conn.commit()

    print(
        f"Loaded {len(synergy_rows)} stratz_hero_synergy rows "
        f"(summed over weeks {weeks}) into '{db_kwargs()['dbname']}'."
    )


if __name__ == "__main__":
    main()
