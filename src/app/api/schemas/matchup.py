from pydantic import BaseModel


class MatchupAdvantageOut(BaseModel):
    hero_id: int
    hero_name: str
    vs_hero_id: int
    wr_a_b: float
    hero_wr: float
    vs_hero_wr: float
    xwr_a_b: float
    advantage: float
    rank_vs_hero: int
