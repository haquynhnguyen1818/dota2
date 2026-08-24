from pydantic import BaseModel


class DraftAnalysisRequest(BaseModel):
    my_hero_id: int
    my_role: str
    ally_picks: list[int]
    enemy_picks: list[int]


class PowerCurvePoint(BaseModel):
    bucket: int
    minutes: str
    my_win_rate: float
    their_win_rate: float
    delta: float


class DraftAnalysisResponse(BaseModel):
    my_hero_id: int
    my_hero_name: str
    my_role: str
    power_curve: list[PowerCurvePoint]
    crossover_bucket: int | None
    crossover_minutes: str | None
    tempo_verdict: str
