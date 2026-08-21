"""Interactive draft-pick suggester: enter your team's picks and opponent picks, get counter-pick suggestions.

For each opponent pick entered (up to 5), accumulates a weighted sum of
`advantage` (from hero_matchup_advantage) against all opponent picks so far,
weighting Support picks at 0.8 and non-Support picks at 1.0. Also accumulates
`synergy` (from stratz_hero_synergy) against your own team's picks so far
(ally_picks), entered once up front. Both deltas are shrunk toward 0 by
sample size (empirical Bayes: delta * n/(n+K)) before summing, since
hero-pair and hero-vs-hero sample sizes vary wildly and small samples would
otherwise dominate the score. After every opponent pick, prints the top 10
best and top 10 worst candidates per role (Carry/Midlane/Offlane), excluding
heroes either team has already taken. See dota2_ranking_adv.txt (Objective 2)
and proj_obj.txt (Phase 2 step 2) for the spec.

Optionally prompts for a player_account_id (Phase 2 step 4) and, if given,
annotates each suggestion with that player's own games_played/win rate on
the hero from player_hero_stats — context only, does not affect ranking or
which heroes get suggested (personal per-hero sample sizes are too small to
trust as a scoring signal).
"""
from collections import defaultdict
from difflib import get_close_matches
from typing import Optional

import psycopg

from app.config import creds_opendota

ROLES = ["Carry", "Midlane", "Offlane"]
MAX_PICKS = 5
TOP_N = 10
SHRINKAGE_K = 500


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


def load_player_history(conn: psycopg.Connection, account_id: int) -> dict[int, tuple[int, int]]:
    rows = conn.execute(
        "SELECT hero_id, games_played, wins FROM player_hero_stats WHERE account_id = %s",
        (account_id,),
    ).fetchall()
    return {hero_id: (games_played, wins) for hero_id, games_played, wins in rows}


def prompt_hero_id(id_by_name: dict[str, int], label: str) -> Optional[int]:
    raw = input(f"{label} (Enter to stop): ").strip()
    if not raw:
        return None
    hero_id = id_by_name.get(raw.lower())
    if hero_id is not None:
        return hero_id
    suggestions = get_close_matches(raw.lower(), id_by_name.keys(), n=3)
    print(f"  Unknown hero '{raw}'.", f"Did you mean: {', '.join(suggestions)}?" if suggestions else "")
    return prompt_hero_id(id_by_name, label)


def _shrink(delta: float, n: int) -> float:
    return delta * (n / (n + SHRINKAGE_K))


def suggestions_by_role(
    conn: psycopg.Connection,
    role: str,
    weight_by_vs_hero: dict[int, float],
    ally_ids: set[int],
    excluded_ids: set[int],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    rows = conn.execute(
        """
        SELECT hma.hero_id, hma.vs_hero_id, hma.advantage, sm.games_played
        FROM hero_matchup_advantage hma
        JOIN stratz_hero_matchups sm ON sm.hero_id = hma.hero_id AND sm.vs_hero_id = hma.vs_hero_id
        WHERE hma.role_name = %s AND hma.vs_hero_id = ANY(%s)
        """,
        (role, list(weight_by_vs_hero)),
    ).fetchall()

    totals: dict[int, float] = defaultdict(float)
    for hero_id, vs_hero_id, advantage, games_played in rows:
        shrunk = _shrink(float(advantage), games_played)
        totals[hero_id] += shrunk * weight_by_vs_hero[vs_hero_id]

    if ally_ids:
        synergy_rows = conn.execute(
            """
            SELECT hero_id, with_hero_id, synergy, games_played
            FROM stratz_hero_synergy
            WHERE with_hero_id = ANY(%s)
            """,
            (list(ally_ids),),
        ).fetchall()
        for hero_id, with_hero_id, synergy, games_played in synergy_rows:
            if hero_id in totals:
                totals[hero_id] += _shrink(float(synergy) / 100, games_played)

    candidates = [(hero_id, total) for hero_id, total in totals.items() if hero_id not in excluded_ids]
    best = sorted(candidates, key=lambda x: x[1], reverse=True)[:TOP_N]
    worst = sorted(candidates, key=lambda x: x[1])[:TOP_N]
    return best, worst


def _history_suffix(hero_id: int, player_history: dict[int, tuple[int, int]]) -> str:
    if hero_id not in player_history:
        return ""
    games_played, wins = player_history[hero_id]
    return f"  (you: {games_played}g, {wins / games_played * 100:.1f}% WR)"


def print_lists(
    name_by_id: dict[int, str],
    role: str,
    best: list[tuple[int, float]],
    worst: list[tuple[int, float]],
    player_history: dict[int, tuple[int, int]],
) -> None:
    print(f"\n-- {role}: top {TOP_N} best --")
    for hero_id, total in best:
        print(f"  {name_by_id[hero_id]:<20} {total * 100:+.2f}%{_history_suffix(hero_id, player_history)}")
    print(f"-- {role}: top {TOP_N} worst --")
    for hero_id, total in worst:
        print(f"  {name_by_id[hero_id]:<20} {total * 100:+.2f}%{_history_suffix(hero_id, player_history)}")


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

        raw_account_id = input("Your OpenDota account id, for personal history (Enter to skip): ").strip()
        player_history = load_player_history(conn, int(raw_account_id)) if raw_account_id else {}

        ally_ids: set[int] = set()
        for pick_num in range(1, MAX_PICKS + 1):
            hero_id = prompt_hero_id(id_by_name, f"Your team's pick {pick_num}")
            if hero_id is None:
                break
            ally_ids.add(hero_id)
            print(f"  -> {name_by_id[hero_id]} added to your team")

        weight_by_vs_hero: dict[int, float] = {}
        for pick_num in range(1, MAX_PICKS + 1):
            hero_id = prompt_hero_id(id_by_name, f"Opponent pick {pick_num}")
            if hero_id is None:
                break
            weight = 0.8 if hero_id in support_ids else 1.0
            weight_by_vs_hero[hero_id] = weight
            print(f"  -> {name_by_id[hero_id]} added (weight {weight})")

            excluded_ids = set(weight_by_vs_hero) | ally_ids
            for role in ROLES:
                best, worst = suggestions_by_role(conn, role, weight_by_vs_hero, ally_ids, excluded_ids)
                print_lists(name_by_id, role, best, worst, player_history)


if __name__ == "__main__":
    main()
