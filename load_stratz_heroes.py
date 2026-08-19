"""Fetch hero identity, base stats, and pick/win/ban time series from Stratz and load them into Postgres."""
from typing import Any

import psycopg
import requests

from database_local import creds_opendota, creds_stratzapi

STRATZ_URL = "https://api.stratz.com/graphql"

HEADERS = {
    "Authorization": f"Bearer {creds_stratzapi['token']}",
    "User-Agent": "STRATZ_API",
}

CONSTANTS_HEROES_QUERY = """
{
  constants {
    heroes {
      id
      name
      displayName
      shortName
      roles { roleId }
      stats {
        attackType
        primaryAttribute
        startingArmor
        startingMagicArmor
        startingDamageMin
        startingDamageMax
        attackRate
        attackAnimationPoint
        attackAcquisitionRange
        attackRange
        strengthBase
        strengthGain
        agilityBase
        agilityGain
        intelligenceBase
        intelligenceGain
        hpRegen
        mpRegen
        moveSpeed
        moveTurnRate
        visionDaytimeRange
        visionNighttimeRange
        complexity
        cMEnabled
      }
    }
  }
}
"""

WIN_WEEK_QUERY = """
query ($heroIds: [Short], $take: Int) {
  heroStats {
    winWeek(heroIds: $heroIds, take: $take) {
      heroId
      week
      durationMinute
      matchCount
      winCount
    }
  }
}
"""

WIN_DAY_QUERY = """
query ($heroIds: [Short], $take: Int) {
  heroStats {
    winDay(heroIds: $heroIds, take: $take) {
      heroId
      day
      matchCount
      winCount
    }
  }
}
"""

BAN_QUERY = """
query ($heroId: Short!, $take: Int) {
  heroStats {
    banDay(heroId: $heroId, take: $take) {
      heroId
      matchCount
      winCount
    }
  }
}
"""

CREATE_STRATZ_HEROES_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_heroes (
    id INTEGER PRIMARY KEY,
    name TEXT,
    display_name TEXT,
    short_name TEXT,
    roles TEXT[],
    primary_attr TEXT,
    attack_type TEXT
)
"""

UPSERT_STRATZ_HERO = """
INSERT INTO stratz_heroes (id, name, display_name, short_name, roles, primary_attr, attack_type)
VALUES (%(id)s, %(name)s, %(display_name)s, %(short_name)s, %(roles)s, %(primary_attr)s, %(attack_type)s)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    display_name = EXCLUDED.display_name,
    short_name = EXCLUDED.short_name,
    roles = EXCLUDED.roles,
    primary_attr = EXCLUDED.primary_attr,
    attack_type = EXCLUDED.attack_type
"""

CREATE_STRATZ_HERO_STATS_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_stats (
    hero_id INTEGER PRIMARY KEY REFERENCES stratz_heroes(id),
    starting_armor NUMERIC,
    starting_magic_armor NUMERIC,
    starting_damage_min NUMERIC,
    starting_damage_max NUMERIC,
    attack_rate NUMERIC,
    attack_animation_point NUMERIC,
    attack_acquisition_range NUMERIC,
    attack_range NUMERIC,
    strength_base NUMERIC,
    strength_gain NUMERIC,
    agility_base NUMERIC,
    agility_gain NUMERIC,
    intelligence_base NUMERIC,
    intelligence_gain NUMERIC,
    hp_regen NUMERIC,
    mp_regen NUMERIC,
    move_speed NUMERIC,
    move_turn_rate NUMERIC,
    vision_daytime_range NUMERIC,
    vision_nighttime_range NUMERIC,
    complexity INTEGER,
    cm_enabled BOOLEAN
)
"""

_HERO_STATS_COLUMNS = [
    "starting_armor", "starting_magic_armor", "starting_damage_min",
    "starting_damage_max", "attack_rate", "attack_animation_point",
    "attack_acquisition_range", "attack_range", "strength_base",
    "strength_gain", "agility_base", "agility_gain", "intelligence_base",
    "intelligence_gain", "hp_regen", "mp_regen", "move_speed",
    "move_turn_rate", "vision_daytime_range", "vision_nighttime_range",
    "complexity", "cm_enabled",
]

UPSERT_STRATZ_HERO_STATS = f"""
INSERT INTO stratz_hero_stats (hero_id, {", ".join(_HERO_STATS_COLUMNS)})
VALUES (%(hero_id)s, {", ".join(f"%({col})s" for col in _HERO_STATS_COLUMNS)})
ON CONFLICT (hero_id) DO UPDATE SET
    {", ".join(f"{col} = EXCLUDED.{col}" for col in _HERO_STATS_COLUMNS)}
"""

CREATE_STRATZ_WIN_WEEK_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_win_week (
    hero_id INTEGER REFERENCES stratz_heroes(id),
    week BIGINT,
    duration_minute INTEGER,
    games_played INTEGER,
    wins INTEGER,
    PRIMARY KEY (hero_id, week, duration_minute)
)
"""

UPSERT_STRATZ_WIN_WEEK = """
INSERT INTO stratz_hero_win_week (hero_id, week, duration_minute, games_played, wins)
VALUES (%(hero_id)s, %(week)s, %(duration_minute)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, week, duration_minute) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""

CREATE_STRATZ_WIN_DAY_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_win_day (
    hero_id INTEGER REFERENCES stratz_heroes(id),
    day BIGINT,
    games_played INTEGER,
    wins INTEGER,
    PRIMARY KEY (hero_id, day)
)
"""

UPSERT_STRATZ_WIN_DAY = """
INSERT INTO stratz_hero_win_day (hero_id, day, games_played, wins)
VALUES (%(hero_id)s, %(day)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, day) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""

CREATE_STRATZ_BANS_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_bans (
    hero_id INTEGER PRIMARY KEY REFERENCES stratz_heroes(id),
    games_played BIGINT,
    wins BIGINT
)
"""

UPSERT_STRATZ_BAN = """
INSERT INTO stratz_hero_bans (hero_id, games_played, wins)
VALUES (%(hero_id)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""


def stratz_query(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(STRATZ_URL, json={"query": query, "variables": variables or {}}, headers=HEADERS)
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch_heroes() -> list[dict[str, Any]]:
    return stratz_query(CONSTANTS_HEROES_QUERY)["constants"]["heroes"]


def hero_row(hero: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": hero["id"],
        "name": hero["name"],
        "display_name": hero["displayName"],
        "short_name": hero["shortName"],
        "roles": [r["roleId"] for r in hero["roles"]],
        "primary_attr": hero["stats"]["primaryAttribute"],
        "attack_type": hero["stats"]["attackType"],
    }


def hero_stats_row(hero: dict[str, Any]) -> dict[str, Any]:
    stats = hero["stats"]
    return {
        "hero_id": hero["id"],
        "starting_armor": stats["startingArmor"],
        "starting_magic_armor": stats["startingMagicArmor"],
        "starting_damage_min": stats["startingDamageMin"],
        "starting_damage_max": stats["startingDamageMax"],
        "attack_rate": stats["attackRate"],
        "attack_animation_point": stats["attackAnimationPoint"],
        "attack_acquisition_range": stats["attackAcquisitionRange"],
        "attack_range": stats["attackRange"],
        "strength_base": stats["strengthBase"],
        "strength_gain": stats["strengthGain"],
        "agility_base": stats["agilityBase"],
        "agility_gain": stats["agilityGain"],
        "intelligence_base": stats["intelligenceBase"],
        "intelligence_gain": stats["intelligenceGain"],
        "hp_regen": stats["hpRegen"],
        "mp_regen": stats["mpRegen"],
        "move_speed": stats["moveSpeed"],
        "move_turn_rate": stats["moveTurnRate"],
        "vision_daytime_range": stats["visionDaytimeRange"],
        "vision_nighttime_range": stats["visionNighttimeRange"],
        "complexity": stats["complexity"],
        "cm_enabled": stats["cMEnabled"],
    }


def fetch_win_week(hero_ids: list[int]) -> list[dict[str, Any]]:
    rows = stratz_query(WIN_WEEK_QUERY, {"heroIds": hero_ids, "take": 2000})["heroStats"]["winWeek"]
    return [
        {
            "hero_id": r["heroId"],
            "week": r["week"],
            "duration_minute": r["durationMinute"],
            "games_played": r["matchCount"],
            "wins": r["winCount"],
        }
        for r in rows
    ]


def fetch_win_day(hero_ids: list[int]) -> list[dict[str, Any]]:
    rows = stratz_query(WIN_DAY_QUERY, {"heroIds": hero_ids, "take": 2000})["heroStats"]["winDay"]
    return [
        {
            "hero_id": r["heroId"],
            "day": r["day"],
            "games_played": r["matchCount"],
            "wins": r["winCount"],
        }
        for r in rows
    ]


def fetch_bans() -> list[dict[str, Any]]:
    # banDay's heroId argument is required but does not filter the result;
    # a single call returns the current ban totals for every hero.
    rows = stratz_query(BAN_QUERY, {"heroId": 1, "take": 200})["heroStats"]["banDay"]
    return [{"hero_id": r["heroId"], "games_played": r["matchCount"], "wins": r["winCount"]} for r in rows]


def main() -> None:
    heroes = fetch_heroes()
    hero_ids = [h["id"] for h in heroes]
    win_week_rows = fetch_win_week(hero_ids)
    win_day_rows = fetch_win_day(hero_ids)
    ban_rows = fetch_bans()

    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_STRATZ_HEROES_TABLE)
            cur.execute(CREATE_STRATZ_HERO_STATS_TABLE)
            cur.execute(CREATE_STRATZ_WIN_WEEK_TABLE)
            cur.execute(CREATE_STRATZ_WIN_DAY_TABLE)
            cur.execute(CREATE_STRATZ_BANS_TABLE)
            cur.executemany(UPSERT_STRATZ_HERO, [hero_row(h) for h in heroes])
            cur.executemany(UPSERT_STRATZ_HERO_STATS, [hero_stats_row(h) for h in heroes])
            cur.executemany(UPSERT_STRATZ_WIN_WEEK, win_week_rows)
            cur.executemany(UPSERT_STRATZ_WIN_DAY, win_day_rows)
            cur.executemany(UPSERT_STRATZ_BAN, ban_rows)
        conn.commit()

    print(
        f"Loaded {len(heroes)} stratz_heroes/stratz_hero_stats rows, "
        f"{len(win_week_rows)} win_week rows, {len(win_day_rows)} win_day rows, "
        f"and {len(ban_rows)} ban rows into '{creds_opendota['db']}'."
    )


if __name__ == "__main__":
    main()
