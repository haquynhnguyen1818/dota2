from pydantic import BaseModel


class DraftRequest(BaseModel):
    opponent_picks: list[int]
    ally_picks: list[int] = []
    player_account_id: int | None = None


class DraftAdvantageBreakdown(BaseModel):
    vs_hero_id: int
    vs_hero_name: str
    advantage: float


class DraftSynergyBreakdown(BaseModel):
    with_hero_id: int
    with_hero_name: str
    synergy: float


class DraftPlayerHistory(BaseModel):
    games_played: int
    wins: int
    win_rate: float


class DraftSuggestion(BaseModel):
    hero_id: int
    hero_name: str
    hero_wr: float
    total_advantage: float
    breakdown: list[DraftAdvantageBreakdown]
    synergy_breakdown: list[DraftSynergyBreakdown]
    player_history: DraftPlayerHistory | None = None


class DraftRoleSuggestions(BaseModel):
    role: str
    best: list[DraftSuggestion]
    worst: list[DraftSuggestion]


class DraftResponse(BaseModel):
    roles: list[DraftRoleSuggestions]
