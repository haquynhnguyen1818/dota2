"""Fetch /heroes, /heroStats and hero matchups from OpenDota and load them into Postgres."""
import time
from typing import Any

import psycopg
import requests

from app.config import creds_opendota

OPENDOTA_BASE_URL = "https://api.opendota.com/api"

RANK_TIERS = {
    1: "herald",
    2: "guardian",
    3: "crusader",
    4: "archon",
    5: "legend",
    6: "ancient",
    7: "divine",
    8: "immortal",
}

CREATE_HEROES_TABLE = """
CREATE TABLE IF NOT EXISTS heroes (
    id INTEGER PRIMARY KEY,
    name TEXT,
    localized_name TEXT,
    primary_attr TEXT,
    attack_type TEXT,
    roles TEXT[]
)
"""

UPSERT_HERO = """
INSERT INTO heroes (id, name, localized_name, primary_attr, attack_type, roles)
VALUES (%(id)s, %(name)s, %(localized_name)s, %(primary_attr)s, %(attack_type)s, %(roles)s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    localized_name = EXCLUDED.localized_name,
    primary_attr = EXCLUDED.primary_attr,
    attack_type = EXCLUDED.attack_type,
    roles = EXCLUDED.roles
"""

_HERO_STATS_RANK_COLUMNS = [
    f"{name}_{suffix}" for name in RANK_TIERS.values() for suffix in ("pick", "win")
]

CREATE_HERO_STATS_TABLE = f"""
CREATE TABLE IF NOT EXISTS hero_stats (
    id INTEGER PRIMARY KEY,
    name TEXT,
    localized_name TEXT,
    primary_attr TEXT,
    attack_type TEXT,
    roles TEXT[],
    img TEXT,
    icon TEXT,
    base_health INTEGER,
    base_health_regen NUMERIC,
    base_mana INTEGER,
    base_mana_regen INTEGER,
    base_armor INTEGER,
    base_mr INTEGER,
    base_attack_min INTEGER,
    base_attack_max INTEGER,
    base_str INTEGER,
    base_agi INTEGER,
    base_int INTEGER,
    str_gain NUMERIC,
    agi_gain NUMERIC,
    int_gain NUMERIC,
    attack_range INTEGER,
    projectile_speed INTEGER,
    attack_rate NUMERIC,
    base_attack_time INTEGER,
    attack_point NUMERIC,
    move_speed INTEGER,
    turn_rate NUMERIC,
    cm_enabled BOOLEAN,
    legs INTEGER,
    day_vision INTEGER,
    night_vision INTEGER,
    turbo_picks INTEGER,
    turbo_wins INTEGER,
    pro_ban INTEGER,
    pro_win INTEGER,
    pro_pick INTEGER,
    {", ".join(f"{col} INTEGER" for col in _HERO_STATS_RANK_COLUMNS)}
)
"""

_HERO_STATS_COLUMNS = [
    "id", "name", "localized_name", "primary_attr", "attack_type", "roles",
    "img", "icon", "base_health", "base_health_regen", "base_mana",
    "base_mana_regen", "base_armor", "base_mr", "base_attack_min",
    "base_attack_max", "base_str", "base_agi", "base_int", "str_gain",
    "agi_gain", "int_gain", "attack_range", "projectile_speed", "attack_rate",
    "base_attack_time", "attack_point", "move_speed", "turn_rate",
    "cm_enabled", "legs", "day_vision", "night_vision", "turbo_picks",
    "turbo_wins", "pro_ban", "pro_win", "pro_pick", *_HERO_STATS_RANK_COLUMNS,
]

UPSERT_HERO_STATS = f"""
INSERT INTO hero_stats ({", ".join(_HERO_STATS_COLUMNS)})
VALUES ({", ".join(f"%({col})s" for col in _HERO_STATS_COLUMNS)})
ON CONFLICT (id) DO UPDATE SET
    {", ".join(f"{col} = EXCLUDED.{col}" for col in _HERO_STATS_COLUMNS if col != "id")}
"""

CREATE_HERO_MATCHUPS_TABLE = """
CREATE TABLE IF NOT EXISTS hero_matchups (
    hero_id INTEGER REFERENCES heroes(id),
    vs_hero_id INTEGER REFERENCES heroes(id),
    games_played INTEGER,
    wins INTEGER,
    PRIMARY KEY (hero_id, vs_hero_id)
)
"""

UPSERT_HERO_MATCHUP = """
INSERT INTO hero_matchups (hero_id, vs_hero_id, games_played, wins)
VALUES (%(hero_id)s, %(vs_hero_id)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, vs_hero_id) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""


def fetch_json(path: str, max_retries: int = 3) -> list[dict[str, Any]]:
    for _ in range(max_retries):
        response = requests.get(f"{OPENDOTA_BASE_URL}{path}")
        if response.status_code == 429:
            time.sleep(61)  # back off a full minute to clear the per-minute quota
            continue
        response.raise_for_status()
        return response.json()
    response.raise_for_status()
    return response.json()


def hero_stats_row(hero: dict[str, Any]) -> dict[str, Any]:
    row = {col: hero.get(col) for col in _HERO_STATS_COLUMNS}
    for tier, name in RANK_TIERS.items():
        row[f"{name}_pick"] = hero.get(f"{tier}_pick")
        row[f"{name}_win"] = hero.get(f"{tier}_win")
    return row


def fetch_hero_matchups(hero_id: int) -> list[dict[str, Any]]:
    matchups = fetch_json(f"/heroes/{hero_id}/matchups")
    return [
        {
            "hero_id": hero_id,
            "vs_hero_id": m["hero_id"],
            "games_played": m["games_played"],
            "wins": m["wins"],
        }
        for m in matchups
    ]


def main() -> None:
    heroes = fetch_json("/heroes")
    hero_stats = fetch_json("/heroStats")

    matchup_rows: list[dict[str, Any]] = []
    for hero in heroes:
        matchup_rows.extend(fetch_hero_matchups(hero["id"]))
        time.sleep(1.5)  # stay under OpenDota's unauthenticated rate limit

    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode="require",
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_HEROES_TABLE)
            cur.execute(CREATE_HERO_STATS_TABLE)
            cur.execute(CREATE_HERO_MATCHUPS_TABLE)
            cur.executemany(UPSERT_HERO, heroes)
            cur.executemany(UPSERT_HERO_STATS, [hero_stats_row(h) for h in hero_stats])
            cur.executemany(UPSERT_HERO_MATCHUP, matchup_rows)
        conn.commit()

    print(
        f"Loaded {len(heroes)} heroes, {len(hero_stats)} hero_stats rows, "
        f"and {len(matchup_rows)} hero_matchups rows into '{creds_opendota['db']}'."
    )


if __name__ == "__main__":
    main()
