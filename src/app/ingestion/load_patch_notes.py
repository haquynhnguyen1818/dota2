"""Fetch the current Dota 2 patch notes from dota2.com and load them into Postgres.

Post-draft coach, Phase F (docs/coaching_plan.md). The point of this is the
*version string*: it pins what the Phase G model is allowed to assume about the
game. The notes themselves ride along as optional prompt context.

Source is the datafeed behind https://www.dota2.com/patches -- the page itself
renders client-side, but it reads two plain JSON endpoints that need no key and
no scraping:

    /datafeed/patchnoteslist              -> every patch, oldest first
    /datafeed/patchnotes?version=7.41e    -> that patch's notes

The feed identifies everything by numeric id and carries no names, so hero,
item and ability names are resolved before rendering: heroes from our own
`heroes` table, items and abilities from OpenDota's constants. All 3 id spaces
resolved 100% against 7.41e, but an unknown id degrades to "Item 208" rather
than raising -- a brand-new patch can name something before OpenDota's
constants catch up.

Both the rendered text and the raw payload are stored. Same call as
`load_stratz_item_timings.py` makes with its per-minute distribution: keeping
the raw response means a better renderer later needs no re-fetch.
"""
import re
from datetime import UTC, datetime
from typing import Any

import psycopg
import requests
from psycopg.types.json import Jsonb

from app.credentials import db_kwargs

PATCH_LIST_URL = "https://www.dota2.com/datafeed/patchnoteslist"
PATCH_NOTES_URL = "https://www.dota2.com/datafeed/patchnotes"
OPENDOTA_CONSTANTS_URL = "https://api.opendota.com/api/constants"

LANGUAGE = "english"

# Valve files summoned units under `heroes`, so the feed carries ids no hero
# list contains. Spirit Bear is the only one across 7.39-7.41e.
NON_HERO_UNITS = {1961: "Spirit Bear"}

CREATE_PATCH_NOTES_TABLE = """
CREATE TABLE IF NOT EXISTS patch_notes (
    version TEXT PRIMARY KEY,
    released_at TIMESTAMPTZ NOT NULL,
    notes_text TEXT NOT NULL,
    raw JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

UPSERT_PATCH_NOTES = """
INSERT INTO patch_notes (version, released_at, notes_text, raw)
VALUES (%s, %s, %s, %s)
ON CONFLICT (version) DO UPDATE SET
    released_at = EXCLUDED.released_at,
    notes_text = EXCLUDED.notes_text,
    raw = EXCLUDED.raw,
    fetched_at = now()
"""

# The only markup the feed emits is <br>, always on a spacer note carrying
# `hide_dot`. Stripping tags empties those, and empty notes are dropped.
_TAG = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    return _TAG.sub(" ", text).strip() if text else ""


def _lines(notes: list[dict[str, Any]] | None, prefix: str = "") -> list[str]:
    out = []
    for note in notes or []:
        text = _clean(note.get("note"))
        if not text:
            continue
        info = _clean(note.get("info"))
        if info:
            text = f"{text} ({info})"
        indent = "  " * (note.get("indent_level", 1) - 1)
        out.append(f"- {indent}{prefix}{text}")
    return out


def _general_blocks(payload: dict[str, Any]) -> list[str]:
    blocks = []
    for group in payload.get("general_notes") or []:
        body = _lines(group.get("generic"))
        if body:
            blocks.append("\n".join([group.get("title") or "General", *body]))
    return blocks


def _item_blocks(entries: list[dict[str, Any]] | None, items: dict[int, str]) -> list[str]:
    blocks: list[str] = []
    heading: str | None = None
    for entry in entries or []:
        # Neutral items are grouped under tier headings that carry no notes.
        if entry.get("is_general_note"):
            heading = f"[{entry.get('title') or ''}]"
            continue
        body = _lines(entry.get("ability_notes"))
        if not body:
            continue
        if heading:
            blocks.append(heading)
            heading = None
        item_id = entry["ability_id"]
        blocks.append("\n".join([items.get(item_id, f"Item {item_id}"), *body]))
    return blocks


def _hero_blocks(
    payload: dict[str, Any], heroes: dict[int, str], abilities: dict[int, str]
) -> list[str]:
    blocks = []
    for hero in payload.get("heroes") or []:
        body = _lines(hero.get("hero_notes"))
        for ability in hero.get("abilities") or []:
            ability_id = ability["ability_id"]
            name = abilities.get(ability_id, f"Ability {ability_id}")
            body += _lines(ability.get("ability_notes"), prefix=f"{name}: ")
        # Talent notes already read "Level 25 Talent ...", so they need no prefix.
        body += _lines(hero.get("talent_notes"))
        if body:
            hero_id = hero["hero_id"]
            name = heroes.get(hero_id) or NON_HERO_UNITS.get(hero_id, f"Hero {hero_id}")
            blocks.append("\n".join([name, *body]))
    return blocks


def render_notes(
    payload: dict[str, Any],
    heroes: dict[int, str],
    items: dict[int, str],
    abilities: dict[int, str],
) -> str:
    """Turn the id-keyed datafeed payload into readable text. Pure."""
    released = released_at(payload).date()
    parts = [f"Dota 2 patch {payload['patch_number']} (released {released})"]
    for title, blocks in (
        ("GENERAL", _general_blocks(payload)),
        ("ITEMS", _item_blocks(payload.get("items"), items)),
        ("NEUTRAL ITEMS", _item_blocks(payload.get("neutral_items"), items)),
        ("HEROES", _hero_blocks(payload, heroes, abilities)),
    ):
        if blocks:
            parts.append(f"== {title} ==")
            parts += blocks
    return "\n\n".join(parts)


def released_at(payload: dict[str, Any]) -> datetime:
    return datetime.fromtimestamp(payload["patch_timestamp"], UTC)


def fetch_latest_version() -> str:
    response = requests.get(PATCH_LIST_URL, params={"language": LANGUAGE}, timeout=30)
    response.raise_for_status()
    # Oldest first, so the current patch is last.
    return response.json()["patches"][-1]["patch_number"]


def fetch_patch_notes(version: str) -> dict[str, Any]:
    response = requests.get(
        PATCH_NOTES_URL, params={"version": version, "language": LANGUAGE}, timeout=30
    )
    response.raise_for_status()
    return response.json()


def fetch_names() -> tuple[dict[int, str], dict[int, str]]:
    """Item and ability display names, both keyed by the ids the feed uses."""
    constants = {}
    for name in ("items", "ability_ids", "abilities"):
        response = requests.get(f"{OPENDOTA_CONSTANTS_URL}/{name}", timeout=60)
        response.raise_for_status()
        constants[name] = response.json()

    items = {
        item["id"]: item.get("dname") or key
        for key, item in constants["items"].items()
        if "id" in item
    }
    abilities = {}
    for ability_id, key in constants["ability_ids"].items():
        name = constants["abilities"].get(key, {}).get("dname") or key
        # OpenDota holds one malformed key, "3060,1617" -- two ids, one ability.
        for part in ability_id.split(","):
            abilities[int(part)] = name
    return items, abilities


def main() -> None:
    version = fetch_latest_version()
    payload = fetch_patch_notes(version)
    items, abilities = fetch_names()

    with psycopg.connect(**db_kwargs()) as conn:
        heroes = dict(conn.execute("SELECT id, localized_name FROM heroes").fetchall())
        notes_text = render_notes(payload, heroes, items, abilities)
        with conn.cursor() as cur:
            cur.execute(CREATE_PATCH_NOTES_TABLE)
            cur.execute(
                UPSERT_PATCH_NOTES,
                (version, released_at(payload), notes_text, Jsonb(payload)),
            )
        conn.commit()

    print(
        f"Loaded patch {version} (released {released_at(payload).date()}): "
        f"{len(notes_text)} chars of notes, "
        f"{len(payload.get('heroes') or [])} heroes changed."
    )


if __name__ == "__main__":
    main()
