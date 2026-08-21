"""Objective 2: draft-pick suggestions from opponent picks and your own team's picks.

Stateless equivalent of engine/draft_suggester.py's interactive loop — the
caller sends the full list of opponent picks (and, optionally, ally picks)
so far on each call (rather than the server tracking session state). Each
candidate's score sums shrunk matchup advantage against opponent picks and
shrunk synergy with ally picks — see draft_suggester.py's module docstring
and proj_obj.txt (Phase 2 step 2) for the empirical-Bayes shrinkage rationale.

If `player_account_id` is given (Phase 2 step 4), each suggestion is also
annotated with that player's own games_played/wins/win_rate on the hero from
`player_hero_stats` (per user decision: annotate only, don't change the
ranking — personal sample sizes are far too small per hero to trust as a
scoring signal without a lot more design work than "attach it as context"
warrants).
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
import psycopg

from app.api.db import get_conn
from app.api.schemas.draft import (
    DraftAdvantageBreakdown,
    DraftPlayerHistory,
    DraftRequest,
    DraftResponse,
    DraftRoleSuggestions,
    DraftSuggestion,
    DraftSynergyBreakdown,
)

router = APIRouter(prefix="/draft-suggestions", tags=["draft-suggestions"])

ROLES = ["Carry", "Midlane", "Offlane"]
MAX_PICKS = 5
TOP_N_BEST = 20
TOP_N_WORST = 10
SHRINKAGE_K = 500


def _shrink(delta: float, n: int) -> float:
    return delta * (n / (n + SHRINKAGE_K))


def _load_support_ids(conn: psycopg.Connection) -> set[int]:
    rows = conn.execute(
        """
        SELECT hr.hero_id
        FROM hero_roles_csv_import hr
        JOIN roles_csv_import r ON r.role_id = hr.role_id
        WHERE r.role_name = 'Supports'
        """
    ).fetchall()
    return {r[0] for r in rows}


def _load_hero_names(conn: psycopg.Connection) -> dict[int, str]:
    rows = conn.execute("SELECT id, localized_name FROM heroes").fetchall()
    return dict(rows)


def _load_player_history(conn: psycopg.Connection, account_id: int) -> dict[int, tuple[int, int]]:
    rows = conn.execute(
        "SELECT hero_id, games_played, wins FROM player_hero_stats WHERE account_id = %s",
        (account_id,),
    ).fetchall()
    return {hero_id: (games_played, wins) for hero_id, games_played, wins in rows}


def _suggestions_by_role(
    conn: psycopg.Connection,
    role: str,
    weight_by_vs_hero: dict[int, float],
    ally_ids: set[int],
    excluded_ids: set[int],
) -> tuple[
    list[tuple[int, float]],
    list[tuple[int, float]],
    dict[int, float],
    dict[int, list[tuple[int, float]]],
    dict[int, list[tuple[int, float]]],
]:
    rows = conn.execute(
        """
        SELECT hma.hero_id, hma.vs_hero_id, hma.advantage, hma.hero_wr, sm.games_played
        FROM hero_matchup_advantage hma
        JOIN stratz_hero_matchups sm ON sm.hero_id = hma.hero_id AND sm.vs_hero_id = hma.vs_hero_id
        WHERE hma.role_name = %s AND hma.vs_hero_id = ANY(%s)
        """,
        (role, list(weight_by_vs_hero)),
    ).fetchall()

    totals: dict[int, float] = defaultdict(float)
    hero_wr_by_id: dict[int, float] = {}
    breakdown_by_id: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for hero_id, vs_hero_id, advantage, hero_wr, games_played in rows:
        shrunk = _shrink(float(advantage), games_played)
        totals[hero_id] += shrunk * weight_by_vs_hero[vs_hero_id]
        hero_wr_by_id[hero_id] = float(hero_wr)
        breakdown_by_id[hero_id].append((vs_hero_id, shrunk))

    synergy_breakdown_by_id: dict[int, list[tuple[int, float]]] = defaultdict(list)
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
                shrunk_synergy = _shrink(float(synergy) / 100, games_played)
                totals[hero_id] += shrunk_synergy
                synergy_breakdown_by_id[hero_id].append((with_hero_id, shrunk_synergy))

    candidates = [(hero_id, total) for hero_id, total in totals.items() if hero_id not in excluded_ids]
    best = sorted(candidates, key=lambda x: x[1], reverse=True)[:TOP_N_BEST]
    worst = sorted(candidates, key=lambda x: x[1])[:TOP_N_WORST]
    return best, worst, hero_wr_by_id, breakdown_by_id, synergy_breakdown_by_id


def _build_suggestion(
    hero_id: int,
    total_advantage: float,
    hero_wr_by_id: dict[int, float],
    breakdown_by_id: dict[int, list[tuple[int, float]]],
    synergy_breakdown_by_id: dict[int, list[tuple[int, float]]],
    player_history_by_id: dict[int, tuple[int, int]],
    name_by_id: dict[int, str],
) -> DraftSuggestion:
    player_history = None
    if hero_id in player_history_by_id:
        games_played, wins = player_history_by_id[hero_id]
        player_history = DraftPlayerHistory(games_played=games_played, wins=wins, win_rate=wins / games_played)

    return DraftSuggestion(
        hero_id=hero_id,
        hero_name=name_by_id[hero_id],
        hero_wr=hero_wr_by_id[hero_id],
        total_advantage=total_advantage,
        breakdown=[
            DraftAdvantageBreakdown(vs_hero_id=vs_id, vs_hero_name=name_by_id[vs_id], advantage=advantage)
            for vs_id, advantage in sorted(breakdown_by_id[hero_id], key=lambda x: x[1], reverse=True)
        ],
        synergy_breakdown=[
            DraftSynergyBreakdown(with_hero_id=with_id, with_hero_name=name_by_id[with_id], synergy=synergy)
            for with_id, synergy in sorted(synergy_breakdown_by_id[hero_id], key=lambda x: x[1], reverse=True)
        ],
        player_history=player_history,
    )


@router.post("", response_model=DraftResponse)
def get_draft_suggestions(request: DraftRequest, conn: psycopg.Connection = Depends(get_conn)) -> DraftResponse:
    if not request.opponent_picks:
        raise HTTPException(status_code=400, detail="opponent_picks must contain at least 1 hero id")
    if len(request.opponent_picks) > MAX_PICKS:
        raise HTTPException(status_code=400, detail=f"opponent_picks must contain at most {MAX_PICKS} hero ids")
    if len(set(request.opponent_picks)) != len(request.opponent_picks):
        raise HTTPException(status_code=400, detail="opponent_picks must not contain duplicates")
    if len(request.ally_picks) > MAX_PICKS:
        raise HTTPException(status_code=400, detail=f"ally_picks must contain at most {MAX_PICKS} hero ids")
    if len(set(request.ally_picks)) != len(request.ally_picks):
        raise HTTPException(status_code=400, detail="ally_picks must not contain duplicates")
    if set(request.opponent_picks) & set(request.ally_picks):
        raise HTTPException(status_code=400, detail="ally_picks and opponent_picks must not overlap")

    name_by_id = _load_hero_names(conn)
    unknown = [h for h in request.opponent_picks + request.ally_picks if h not in name_by_id]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown hero id(s): {unknown}")

    player_history_by_id: dict[int, tuple[int, int]] = {}
    if request.player_account_id is not None:
        known_player = conn.execute(
            "SELECT 1 FROM players WHERE account_id = %s", (request.player_account_id,)
        ).fetchone()
        if not known_player:
            raise HTTPException(status_code=404, detail=f"Unknown player_account_id: {request.player_account_id}")
        player_history_by_id = _load_player_history(conn, request.player_account_id)

    support_ids = _load_support_ids(conn)
    weight_by_vs_hero = {hero_id: (0.8 if hero_id in support_ids else 1.0) for hero_id in request.opponent_picks}
    ally_ids = set(request.ally_picks)
    excluded_ids = set(weight_by_vs_hero) | ally_ids

    roles = []
    for role in ROLES:
        best, worst, hero_wr_by_id, breakdown_by_id, synergy_breakdown_by_id = _suggestions_by_role(
            conn, role, weight_by_vs_hero, ally_ids, excluded_ids
        )
        roles.append(
            DraftRoleSuggestions(
                role=role,
                best=[
                    _build_suggestion(
                        h, t, hero_wr_by_id, breakdown_by_id, synergy_breakdown_by_id, player_history_by_id, name_by_id
                    )
                    for h, t in best
                ],
                worst=[
                    _build_suggestion(
                        h, t, hero_wr_by_id, breakdown_by_id, synergy_breakdown_by_id, player_history_by_id, name_by_id
                    )
                    for h, t in worst
                ],
            )
        )

    return DraftResponse(roles=roles)
