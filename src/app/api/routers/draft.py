"""Objective 2: draft-pick suggestions from a set of opponent picks.

Stateless equivalent of engine/draft_suggester.py's interactive loop — the
caller sends the full list of opponent picks so far on each call (rather
than the server tracking session state).
"""
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
import psycopg

from app.api.db import get_conn
from app.api.schemas.draft import (
    DraftAdvantageBreakdown,
    DraftRequest,
    DraftResponse,
    DraftRoleSuggestions,
    DraftSuggestion,
)

router = APIRouter(prefix="/draft-suggestions", tags=["draft-suggestions"])

ROLES = ["Carry", "Midlane", "Offlane"]
MAX_PICKS = 5
TOP_N_BEST = 20
TOP_N_WORST = 10


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


def _suggestions_by_role(
    conn: psycopg.Connection,
    role: str,
    weight_by_vs_hero: dict[int, float],
) -> tuple[list[tuple[int, float]], list[tuple[int, float]], dict[int, float], dict[int, list[tuple[int, float]]]]:
    rows = conn.execute(
        """
        SELECT hero_id, vs_hero_id, advantage, hero_wr
        FROM hero_matchup_advantage
        WHERE role_name = %s AND vs_hero_id = ANY(%s)
        """,
        (role, list(weight_by_vs_hero)),
    ).fetchall()

    totals: dict[int, float] = defaultdict(float)
    hero_wr_by_id: dict[int, float] = {}
    breakdown_by_id: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for hero_id, vs_hero_id, advantage, hero_wr in rows:
        advantage = float(advantage)
        totals[hero_id] += advantage * weight_by_vs_hero[vs_hero_id]
        hero_wr_by_id[hero_id] = float(hero_wr)
        breakdown_by_id[hero_id].append((vs_hero_id, advantage))

    candidates = [(hero_id, total) for hero_id, total in totals.items() if hero_id not in weight_by_vs_hero]
    best = sorted(candidates, key=lambda x: x[1], reverse=True)[:TOP_N_BEST]
    worst = sorted(candidates, key=lambda x: x[1])[:TOP_N_WORST]
    return best, worst, hero_wr_by_id, breakdown_by_id


def _build_suggestion(
    hero_id: int,
    total_advantage: float,
    hero_wr_by_id: dict[int, float],
    breakdown_by_id: dict[int, list[tuple[int, float]]],
    name_by_id: dict[int, str],
) -> DraftSuggestion:
    return DraftSuggestion(
        hero_id=hero_id,
        hero_name=name_by_id[hero_id],
        hero_wr=hero_wr_by_id[hero_id],
        total_advantage=total_advantage,
        breakdown=[
            DraftAdvantageBreakdown(vs_hero_id=vs_id, vs_hero_name=name_by_id[vs_id], advantage=advantage)
            for vs_id, advantage in sorted(breakdown_by_id[hero_id], key=lambda x: x[1], reverse=True)
        ],
    )


@router.post("", response_model=DraftResponse)
def get_draft_suggestions(request: DraftRequest, conn: psycopg.Connection = Depends(get_conn)) -> DraftResponse:
    if not request.opponent_picks:
        raise HTTPException(status_code=400, detail="opponent_picks must contain at least 1 hero id")
    if len(request.opponent_picks) > MAX_PICKS:
        raise HTTPException(status_code=400, detail=f"opponent_picks must contain at most {MAX_PICKS} hero ids")
    if len(set(request.opponent_picks)) != len(request.opponent_picks):
        raise HTTPException(status_code=400, detail="opponent_picks must not contain duplicates")

    name_by_id = _load_hero_names(conn)
    unknown = [h for h in request.opponent_picks if h not in name_by_id]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown hero id(s): {unknown}")

    support_ids = _load_support_ids(conn)
    weight_by_vs_hero = {hero_id: (0.8 if hero_id in support_ids else 1.0) for hero_id in request.opponent_picks}

    roles = []
    for role in ROLES:
        best, worst, hero_wr_by_id, breakdown_by_id = _suggestions_by_role(conn, role, weight_by_vs_hero)
        roles.append(
            DraftRoleSuggestions(
                role=role,
                best=[_build_suggestion(h, t, hero_wr_by_id, breakdown_by_id, name_by_id) for h, t in best],
                worst=[_build_suggestion(h, t, hero_wr_by_id, breakdown_by_id, name_by_id) for h, t in worst],
            )
        )

    return DraftResponse(roles=roles)
