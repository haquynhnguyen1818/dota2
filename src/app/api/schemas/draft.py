from pydantic import BaseModel


class DraftRequest(BaseModel):
    opponent_picks: list[int]


class DraftSuggestion(BaseModel):
    hero_id: int
    hero_name: str
    total_advantage: float


class DraftRoleSuggestions(BaseModel):
    role: str
    best: list[DraftSuggestion]
    worst: list[DraftSuggestion]


class DraftResponse(BaseModel):
    roles: list[DraftRoleSuggestions]
