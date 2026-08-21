"""Interactive draft-pick suggester: enter opponent picks, get counter-pick suggestions.

For each opponent pick entered (up to 5), accumulates a weighted sum of
`advantage` (from hero_matchup_advantage) against all opponent picks so far,
weighting Support picks at 0.8 and non-Support picks at 1.0. After every pick,
prints the top 10 best and top 10 worst candidates per role (Carry/Midlane/
Offlane), excluding heroes the opponent has already taken. See
dota2_ranking_adv.txt (Objective 2) for the spec.
"""
from collections import defaultdict
from difflib import get_close_matches
from typing import Optional

import psycopg

from app.config import creds_opendota

ROLES = ["Carry", "Midlane", "Offlane"]
MAX_PICKS = 5
TOP_N = 10


def load_heroes(conn: psycopg.Connection) -> tuple[dict[str, int], dict[int, str]]:
    rows = conn.execute("SELECT id, localized_name FROM heroes").fetchall()
    id_by_name = {name.lower(): hero_id for hero_id, name in rows}
    name_by_id = {hero_id: name for hero_id, name in rows}
    return id_by_name, name_by_id


def load_support_ids(conn: psycopg.Connection) -> set[int]:
    rows = conn.execute(
        """
        SELECT hr.hero_id
        FROM hero_roles_csv_import hr
        JOIN roles_csv_import r ON r.role_id = hr.role_id
        WHERE r.role_name = 'Supports'
        """
    ).fetchall()
    return {r[0] for r in rows}


def prompt_hero_id(id_by_name: dict[str, int], pick_num: int) -> Optional[int]:
    raw = input(f"Opponent pick {pick_num} (Enter to stop): ").strip()
    if not raw:
        return None
    hero_id = id_by_name.get(raw.lower())
    if hero_id is not None:
        return hero_id
    suggestions = get_close_matches(raw.lower(), id_by_name.keys(), n=3)
    print(f"  Unknown hero '{raw}'.", f"Did you mean: {', '.join(suggestions)}?" if suggestions else "")
    return prompt_hero_id(id_by_name, pick_num)


def suggestions_by_role(
    conn: psycopg.Connection,
    role: str,
    weight_by_vs_hero: dict[int, float],
    excluded_ids: set[int],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    rows = conn.execute(
        """
        SELECT hero_id, vs_hero_id, advantage
        FROM hero_matchup_advantage
        WHERE role_name = %s AND vs_hero_id = ANY(%s)
        """,
        (role, list(weight_by_vs_hero)),
    ).fetchall()

    totals: dict[int, float] = defaultdict(float)
    for hero_id, vs_hero_id, advantage in rows:
        totals[hero_id] += float(advantage) * weight_by_vs_hero[vs_hero_id]

    candidates = [(hero_id, total) for hero_id, total in totals.items() if hero_id not in excluded_ids]
    best = sorted(candidates, key=lambda x: x[1], reverse=True)[:TOP_N]
    worst = sorted(candidates, key=lambda x: x[1])[:TOP_N]
    return best, worst


def print_lists(name_by_id: dict[int, str], role: str, best: list[tuple[int, float]], worst: list[tuple[int, float]]) -> None:
    print(f"\n-- {role}: top {TOP_N} best --")
    for hero_id, total in best:
        print(f"  {name_by_id[hero_id]:<20} {total * 100:+.2f}%")
    print(f"-- {role}: top {TOP_N} worst --")
    for hero_id, total in worst:
        print(f"  {name_by_id[hero_id]:<20} {total * 100:+.2f}%")


def main() -> None:
    with psycopg.connect(
        host=creds_opendota["host"],
        port=creds_opendota["port"],
        user=creds_opendota["user"],
        password=creds_opendota["pw"],
        dbname=creds_opendota["db"],
        sslmode=creds_opendota.get("sslmode", "require"),
    ) as conn:
        id_by_name, name_by_id = load_heroes(conn)
        support_ids = load_support_ids(conn)

        weight_by_vs_hero: dict[int, float] = {}
        for pick_num in range(1, MAX_PICKS + 1):
            hero_id = prompt_hero_id(id_by_name, pick_num)
            if hero_id is None:
                break
            weight = 0.8 if hero_id in support_ids else 1.0
            weight_by_vs_hero[hero_id] = weight
            print(f"  -> {name_by_id[hero_id]} added (weight {weight})")

            for role in ROLES:
                best, worst = suggestions_by_role(conn, role, weight_by_vs_hero, set(weight_by_vs_hero))
                print_lists(name_by_id, role, best, worst)


if __name__ == "__main__":
    main()
