from pydantic import BaseModel

from app.engine.coach import DEFAULT_LANGUAGE, CoachPlan


class CoachPlanRequest(BaseModel):
    my_hero_id: int
    my_role: str | None = None
    ally_picks: list[int]
    enemy_picks: list[int]
    language: str = DEFAULT_LANGUAGE


class CoachPlanResponse(CoachPlan):
    my_hero_id: int
    my_hero_name: str
    cached: bool


class UnlockRequest(BaseModel):
    pin: str


class RateLimitStatus(BaseModel):
    calls_used: int
    limit: int
