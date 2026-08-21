from pydantic import BaseModel


class DraftRequest(BaseModel):
    opponent_picks: list[int]


class DraftAdvantageBreakdown(BaseModel):
    vs_hero_id: int
    vs_hero_name: str
    advantage: float


class DraftSuggestion(BaseModel):
    hero_id: int
    hero_name: str
    hero_wr: float
    total_advantage: float
    breakdown: list[DraftAdvantageBreakdown]


class DraftRoleSuggestions(BaseModel):
    role: str
    best: list[DraftSuggestion]
    worst: list[DraftSuggestion]


class DraftResponse(BaseModel):
    roles: list[DraftRoleSuggestions]
