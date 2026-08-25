"""Post-draft coach: the power curve for a completed 5v5.

Phase B3 of docs/coaching_plan.md. Distinct from `/draft-suggestions`, which
answers "who should I pick next?" mid-draft from partial picks. This fires only
once both teams are full, so it requires exactly 5 and 5.

Scoring lives in `engine/draft_context.py`; this router validates input, loads
the duration stats, and shapes the response.
"""
from fastapi import APIRouter, Depends, HTTPException
import psycopg

from app.api.db import get_conn
from app.api.schemas.analysis import (
    DraftAnalysisRequest,
    DraftAnalysisResponse,
    PowerCurvePoint,
)
from app.engine.draft_context import bucket_label, build_context, load_bucket_stats

router = APIRouter(prefix="/draft-analysis", tags=["draft-analysis"])

TEAM_SIZE = 5

# Reuses the role vocabulary already in roles_csv_import rather than inventing
# a new one. my_role is optional context carried through for the LLM phase; the
# power curve doesn't read it, and the UI dropped the selector for now, so it is
# only validated when actually supplied.
ROLES = {"Carry", "Midlane", "Offlane", "Supports"}


def _load_hero_names(conn: psycopg.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT id, localized_name FROM heroes").fetchall())


@router.post("", response_model=DraftAnalysisResponse)
def get_draft_analysis(
    request: DraftAnalysisRequest, conn: psycopg.Connection = Depends(get_conn)
) -> DraftAnalysisResponse:
    for field, picks in (("ally_picks", request.ally_picks), ("enemy_picks", request.enemy_picks)):
        if len(picks) != TEAM_SIZE:
            raise HTTPException(status_code=400, detail=f"{field} must contain exactly {TEAM_SIZE} hero ids")
        if len(set(picks)) != len(picks):
            raise HTTPException(status_code=400, detail=f"{field} must not contain duplicates")
    if set(request.ally_picks) & set(request.enemy_picks):
        raise HTTPException(status_code=400, detail="ally_picks and enemy_picks must not overlap")
    if request.my_hero_id not in request.ally_picks:
        raise HTTPException(status_code=400, detail="my_hero_id must be one of ally_picks")
    if request.my_role is not None and request.my_role not in ROLES:
        raise HTTPException(status_code=400, detail=f"my_role must be one of {sorted(ROLES)}")

    name_by_id = _load_hero_names(conn)
    unknown = [h for h in request.ally_picks + request.enemy_picks if h not in name_by_id]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown hero id(s): {unknown}")

    stats = load_bucket_stats(conn, request.ally_picks + request.enemy_picks)
    context = build_context(
        request.my_hero_id, request.my_role, request.ally_picks, request.enemy_picks, stats
    )

    return DraftAnalysisResponse(
        my_hero_id=context.my_hero_id,
        my_hero_name=name_by_id[context.my_hero_id],
        my_role=context.my_role,
        power_curve=[
            PowerCurvePoint(
                bucket=p.bucket,
                minutes=p.minutes,
                my_win_rate=p.my_win_rate,
                their_win_rate=p.their_win_rate,
                delta=p.delta,
            )
            for p in context.power_curve
        ],
        crossover_bucket=context.crossover_bucket,
        crossover_minutes=bucket_label(context.crossover_bucket) if context.crossover_bucket else None,
        tempo_verdict=context.tempo_verdict,
    )
