"""Load curated player identities from docs/players_id.txt, then fetch each
public profile's per-hero history from OpenDota. Private profiles are loaded
into the `players` identity table (so we know about them) but skipped for
history — OpenDota returns all-zero data for private profiles, and the user
tracks public/private status by hand in players_id.txt, updating it once a
profile is made public.
"""
import re
import time
from pathlib import Path
from typing import Any

import psycopg
import requests

from app.config import creds_opendota

OPENDOTA_BASE_URL = "https://api.opendota.com/api"

PLAYERS_FILE = Path(__file__).resolve().parents[3] / "docs" / "players_id.txt"

PLAYER_LINE_RE = re.compile(
    r"^(?P<name>.+?):\s*(?P<account_id>\d+)\.\s*Profile status:\s*(?P<status>public|private)\.?\s*$",
    re.IGNORECASE,
)

CREATE_PLAYERS_TABLE = """
CREATE TABLE IF NOT EXISTS players (
    account_id BIGINT PRIMARY KEY,
    player_name TEXT,
    is_public BOOLEAN NOT NULL
)
"""

UPSERT_PLAYER = """
INSERT INTO players (account_id, player_name, is_public)
VALUES (%(account_id)s, %(player_name)s, %(is_public)s)
ON CONFLICT (account_id) DO UPDATE SET
    player_name = EXCLUDED.player_name,
    is_public = EXCLUDED.is_public
"""

CREATE_PLAYER_HERO_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS player_hero_stats (
    account_id BIGINT REFERENCES players(account_id),
    hero_id INTEGER REFERENCES heroes(id),
    games_played INTEGER,
    wins INTEGER,
    with_games_played INTEGER,
    with_wins INTEGER,
    against_games_played INTEGER,
    against_wins INTEGER,
    last_played BIGINT,
    PRIMARY KEY (account_id, hero_id)
)
"""

UPSERT_PLAYER_HERO_STATS = """
INSERT INTO player_hero_stats
    (account_id, hero_id, games_played, wins, with_games_played, with_wins,
     against_games_played, against_wins, last_played)
VALUES
    (%(account_id)s, %(hero_id)s, %(games_played)s, %(wins)s, %(with_games_played)s,
     %(with_wins)s, %(against_games_played)s, %(against_wins)s, %(last_played)s)
ON CONFLICT (account_id, hero_id) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins,
    with_games_played = EXCLUDED.with_games_played,
    with_wins = EXCLUDED.with_wins,
    against_games_played = EXCLUDED.against_games_played,
    against_wins = EXCLUDED.against_wins,
    last_played = EXCLUDED.last_played
"""


def parse_players_file() -> list[dict[str, Any]]:
    players = []
    for line in PLAYERS_FILE.read_text(encoding="utf-8").splitlines():
        match = PLAYER_LINE_RE.match(line.strip())
        if not match:
            continue
        players.append(
            {
                "account_id": int(match.group("account_id")),
                "player_name": match.group("name").strip(),
                "is_public": match.group("status").lower() == "public",
            }
        )
    return players


def fetch_json(path: str, max_retries: int = 3) -> Any:
    for _ in range(max_retries):
        response = requests.get(f"{OPENDOTA_BASE_URL}{path}")
        if response.status_code == 429:
            time.sleep(61)  # back off a full minute to clear the per-minute quota
            continue
        response.raise_for_status()
        return response.json()
    response.raise_for_status()
    return response.json()


def fetch_player_hero_stats(account_id: int) -> list[dict[str, Any]]:
    rows = fetch_json(f"/players/{account_id}/heroes")
    return [
        {
            "account_id": account_id,
            "hero_id": r["hero_id"],
            "games_played": r["games"],
            "wins": r["win"],
            "with_games_played": r["with_games"],
            "with_wins": r["with_win"],
            "against_games_played": r["against_games"],
            "against_wins": r["against_win"],
            "last_played": r["last_played"],
        }
        for r in rows
        if r["games"] > 0
    ]


def main() -> None:
    players = parse_players_file()
    public_players = [p for p in players if p["is_public"]]

    hero_stats_rows: list[dict[str, Any]] = []
    for player in public_players:
        hero_stats_rows.extend(fetch_player_hero_stats(player["account_id"]))
        time.sleep(1.5)  # stay under OpenDota's unauthenticated rate limit

    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode=creds_opendota.get("sslmode", "require"),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_PLAYERS_TABLE)
            cur.execute(CREATE_PLAYER_HERO_STATS_TABLE)
            cur.executemany(UPSERT_PLAYER, players)
            cur.executemany(UPSERT_PLAYER_HERO_STATS, hero_stats_rows)
        conn.commit()

    skipped = [p["player_name"] for p in players if not p["is_public"]]
    print(
        f"Loaded {len(players)} players ({len(public_players)} public) and "
        f"{len(hero_stats_rows)} player_hero_stats rows into '{creds_opendota['db']}'. "
        f"Skipped history for private profiles: {skipped}"
    )


if __name__ == "__main__":
    main()
