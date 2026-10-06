from pydantic import BaseModel


class HeroMatchupOut(BaseModel):
    """One opponent, from the selected hero's point of view."""

    vs_hero_id: int
    vs_hero_name: str
    wr_a_b: float
    vs_hero_wr: float
    advantage: float


class HeroMatchupsOut(BaseModel):
    """A hero's own win rate plus its edge against every other hero.

    `matchups` is sorted by `advantage` descending, so the caller splits the
    head off for advantages and the tail for disadvantages rather than this
    endpoint deciding how many of each to show.
    """

    hero_id: int
    hero_name: str
    hero_wr: float
    matchups: list[HeroMatchupOut]
