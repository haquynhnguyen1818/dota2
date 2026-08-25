"""Post-draft coach: LLM synthesis over the deterministic context.

Phase G of docs/coaching_plan.md. Builds on the same signals as
`/draft-analysis` but adds one Claude call that turns the numbers into a short
natural-language plan. Kept as its own endpoint, not folded into
`/draft-analysis`, because this one costs money and hits an LLM -- the power
curve endpoint stays free, deterministic, and instant.
"""
from hmac import compare_digest

from fastapi import APIRouter, Depends, HTTPException
import anthropic
import psycopg

from app.api.db import get_conn
from app.api.schemas.coach import CoachPlanRequest, CoachPlanResponse, RateLimitStatus, UnlockRequest
from app.credentials import coach_pin
from app.engine.coach import (
    RATE_WINDOW_MINUTES,
    build_prompt,
    cache_key,
    effective_limit,
    generate_plan,
    is_rate_limited,
    load_cached_plan,
    load_rate_limit_counts,
    record_call,
    record_unlock,
    store_plan,
)
from app.engine.draft_context import build_context, load_context_data

router = APIRouter(prefix="/coach", tags=["coach"])

TEAM_SIZE = 5

# Same vocabulary as /draft-analysis (app/api/routers/analysis.py).
ROLES = {"Carry", "Midlane", "Offlane", "Supports"}

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    """Lazy singleton so a missing ANTHROPIC_API_KEY only breaks this router,
    not the whole API, at construction time."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _load_hero_names(conn: psycopg.Connection) -> dict[int, str]:
    return dict(conn.execute("SELECT id, localized_name FROM heroes").fetchall())


@router.post("", response_model=CoachPlanResponse)
def get_coach_plan(
    request: CoachPlanRequest,
    conn: psycopg.Connection = Depends(get_conn),
    client: anthropic.Anthropic = Depends(get_client),
) -> CoachPlanResponse:
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

    names = _load_hero_names(conn)
    unknown = [h for h in request.ally_picks + request.enemy_picks if h not in names]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown hero id(s): {unknown}")

    key = cache_key(request.my_hero_id, request.my_role, request.ally_picks, request.enemy_picks)
    plan = load_cached_plan(conn, key)
    cached = plan is not None
    if plan is None:
        # Only a real Claude call is rate-limited -- a cache hit above never
        # reaches here, so re-viewing a draft you already paid for is free.
        calls, unlocks = load_rate_limit_counts(conn)
        if is_rate_limited(calls, unlocks):
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limited",
                    "calls_used": calls,
                    "limit": effective_limit(unlocks),
                    "message": (
                        f"Coach call limit reached ({effective_limit(unlocks)} per "
                        f"{RATE_WINDOW_MINUTES} min). POST /coach/unlock with the PIN for more."
                    ),
                },
            )

        data = load_context_data(conn, request.ally_picks + request.enemy_picks)
        context = build_context(
            request.my_hero_id, request.my_role, request.ally_picks, request.enemy_picks, data
        )
        prompt = build_prompt(context, names, request.ally_picks, request.enemy_picks)
        plan = generate_plan(client, prompt)
        record_call(conn)
        store_plan(conn, key, plan)

    return CoachPlanResponse(
        my_hero_id=request.my_hero_id,
        my_hero_name=names[request.my_hero_id],
        cached=cached,
        **plan.model_dump(),
    )


@router.post("/unlock", response_model=RateLimitStatus)
def unlock_coach_calls(
    request: UnlockRequest, conn: psycopg.Connection = Depends(get_conn)
) -> RateLimitStatus:
    configured_pin = coach_pin()
    if not configured_pin:
        raise HTTPException(status_code=500, detail="COACH_PIN is not configured")
    if not compare_digest(request.pin, configured_pin):
        raise HTTPException(status_code=403, detail="Incorrect PIN")

    record_unlock(conn)
    calls, unlocks = load_rate_limit_counts(conn)
    return RateLimitStatus(calls_used=calls, limit=effective_limit(unlocks))
