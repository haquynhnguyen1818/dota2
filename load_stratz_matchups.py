"""Fetch hero-vs-hero matchup data from the Stratz GraphQL API and load it into Postgres."""
from typing import Any

import psycopg
import requests

from database_local import creds_opendota, creds_stratzapi

STRATZ_URL = "https://api.stratz.com/graphql"

MATCHUP_QUERY = """
query ($heroIds: [Short], $take: Int) {
  heroStats {
    matchUp(heroIds: $heroIds, take: $take) {
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


def fetch_hero_matchups(hero_ids: list[int]) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {creds_stratzapi['token']}",
        "User-Agent": "STRATZ_API",
    }
    response = requests.post(
        STRATZ_URL,
        json={"query": MATCHUP_QUERY, "variables": {"heroIds": hero_ids, "take": 200}},
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
    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
    ) as conn:
        hero_ids = [r[0] for r in conn.execute("SELECT id FROM heroes ORDER BY id").fetchall()]
        matchup_rows = fetch_hero_matchups(hero_ids)

        with conn.cursor() as cur:
            cur.execute(CREATE_STRATZ_MATCHUPS_TABLE)
            cur.executemany(UPSERT_STRATZ_MATCHUP, matchup_rows)
        conn.commit()

    print(f"Loaded {len(matchup_rows)} stratz_hero_matchups rows into '{creds_opendota['db']}'.")


if __name__ == "__main__":
    main()
