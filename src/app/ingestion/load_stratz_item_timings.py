"""Fetch item names and per-hero item purchase timings from Stratz into Postgres.

Backs the post-draft coach's `enemy_clocks` (docs/coaching_plan.md, Phase E2).

The original plan assumed timings would need parsed matches (`purchase_log`) and
suggested approximating from GPM / item cost. That turned out to be unnecessary:
`heroStats.itemFullPurchase` works on the free token and returns the full
per-minute purchase distribution, so real medians are available rather than an
approximation.

Stores the raw distribution, not a precomputed median — same split as the rest
of `ingestion/`, and it leaves p25/p75 or win-rate-weighted timings available
later without a re-fetch.

Three things to know before using this table:
  * `minute` is Stratz's `time` field, already in minutes.
  * **`instance` is which copy of the item this is** — 0 is the first purchase,
    and values run up to 3 for items heroes stack. It is part of the primary
    key. Threat timings want `instance = 0`, the first time the enemy gets the
    item. Leaving it out of the key silently overwrites one instance with
    another and corrupts the counts for the ~4% of (item, minute) cells
    affected; it cost 5,154 rows before it was caught.
  * It covers **build-up components too**, not just finished items — Anti-Mage's
    list includes Perseverance and Yasha alongside Battle Fury and Manta Style.
    Deciding which item counts as a "threat" is a scoring question, deliberately
    left to Phase E4 rather than filtered away here.

`heroId` is singular on this endpoint, so this is 1 call per hero per week —
254 in total, throttled to stay inside Stratz's 250/min limit.
"""
import time
from typing import Any

import psycopg
import requests

from app.credentials import db_kwargs, stratz_headers

STRATZ_URL = "https://api.stratz.com/graphql"

HEADERS = stratz_headers()

RECENT_WEEKS = 2
REQUEST_DELAY_SECONDS = 0.3  # ~200 calls/min, under Stratz's 250/min ceiling

ITEMS_QUERY = """
{
  constants {
    items {
      id
      shortName
      displayName
      components {
        componentId
      }
    }
  }
}
"""

ITEM_PURCHASE_QUERY = """
query ($heroId: Short!, $week: Long) {
  heroStats {
    itemFullPurchase(heroId: $heroId, week: $week) {
      itemId
      instance
      time
      matchCount
      winCount
    }
  }
}
"""

CREATE_ITEMS_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_items (
    id INTEGER PRIMARY KEY,
    short_name TEXT,
    display_name TEXT,
    is_component BOOLEAN
)
"""

UPSERT_ITEM = """
INSERT INTO stratz_items (id, short_name, display_name, is_component)
VALUES (%(id)s, %(short_name)s, %(display_name)s, %(is_component)s)
ON CONFLICT (id) DO UPDATE SET
    short_name = EXCLUDED.short_name,
    display_name = EXCLUDED.display_name,
    is_component = EXCLUDED.is_component
"""

CREATE_PURCHASES_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_item_purchase (
    hero_id INTEGER REFERENCES stratz_heroes(id),
    week BIGINT,
    item_id INTEGER,
    instance INTEGER,
    minute INTEGER,
    games_played BIGINT,
    wins BIGINT,
    PRIMARY KEY (hero_id, week, item_id, instance, minute)
)
"""

UPSERT_PURCHASE = """
INSERT INTO stratz_hero_item_purchase (hero_id, week, item_id, instance, minute, games_played, wins)
VALUES (%(hero_id)s, %(week)s, %(item_id)s, %(instance)s, %(minute)s, %(games_played)s, %(wins)s)
ON CONFLICT (hero_id, week, item_id, instance, minute) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    wins = EXCLUDED.wins
"""


def stratz_query(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(
        STRATZ_URL, json={"query": query, "variables": variables or {}}, headers=HEADERS, timeout=90
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def _clean(value: str | None) -> str | None:
    """Drop NUL bytes, which Postgres text columns reject outright.

    A couple of recipe placeholders come back from Stratz with displayName set
    to a lone "\\x00" (and a couple more as null) — e.g. recipe_eagle_eye and
    recipe_diffusal_blade_2. Sanitised rather than skipped by id, so a new bad
    row later doesn't break the load.
    """
    if value is None:
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned or None


def fetch_items() -> list[dict[str, Any]]:
    """Item constants, flagged with whether each is a build-up part of something else.

    `is_component` is derived, not given: an item is a component if any other
    item lists it in `components`. It separates Perseverance/Yasha/Sange from
    Battle Fury/Manta/BKB, which is what `enemy_clocks` needs.

    Known wart: **Blink Dagger flags as a component** because Overwhelming and
    Arcane Blink build from it, even though its own timing is a real threat.
    So treat this as one input to picking threat items, not the whole rule.
    """
    items = stratz_query(ITEMS_QUERY)["constants"]["items"]
    component_ids = {c["componentId"] for i in items for c in (i["components"] or [])}
    return [
        {
            "id": i["id"],
            "short_name": _clean(i["shortName"]),
            "display_name": _clean(i["displayName"]),
            "is_component": i["id"] in component_ids,
        }
        for i in items
    ]


def fetch_purchases(hero_id: int, week: int) -> list[dict[str, Any]]:
    rows = stratz_query(ITEM_PURCHASE_QUERY, {"heroId": hero_id, "week": week})["heroStats"][
        "itemFullPurchase"
    ]
    return [
        {
            "hero_id": hero_id,
            "week": week,
            "item_id": r["itemId"],
            "instance": r["instance"],
            "minute": r["time"],
            "games_played": r["matchCount"],
            "wins": r["winCount"],
        }
        for r in rows
    ]


def main() -> None:
    items = fetch_items()

    with psycopg.connect(**db_kwargs()) as conn:
        hero_ids = [r[0] for r in conn.execute("SELECT id FROM stratz_heroes ORDER BY id").fetchall()]
        weeks = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT week FROM stratz_hero_win_week ORDER BY week DESC LIMIT {RECENT_WEEKS}"
            ).fetchall()
        ]

        with conn.cursor() as cur:
            cur.execute(CREATE_ITEMS_TABLE)
            cur.execute(CREATE_PURCHASES_TABLE)
            cur.executemany(UPSERT_ITEM, items)
        conn.commit()

        total = 0
        for week in weeks:
            for hero_id in hero_ids:
                rows = fetch_purchases(hero_id, week)
                with conn.cursor() as cur:
                    cur.executemany(UPSERT_PURCHASE, rows)
                total += len(rows)
                time.sleep(REQUEST_DELAY_SECONDS)
            conn.commit()

    print(
        f"Loaded {len(items)} stratz_items rows and {total} stratz_hero_item_purchase rows "
        f"({len(hero_ids)} heroes over weeks {weeks}) into '{db_kwargs()['dbname']}'."
    )


if __name__ == "__main__":
    main()
