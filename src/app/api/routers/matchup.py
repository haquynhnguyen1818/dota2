"""Objective 1: ranked matchup-advantage list per role for a given opponent hero."""
from fastapi import APIRouter, Depends, HTTPException
import psycopg

from app.api.db import get_conn
from app.api.schemas.matchup import MatchupAdvantageOut

router = APIRouter(prefix="/matchup-advantage", tags=["matchup-advantage"])

VALID_ROLES = {"Carry", "Midlane", "Offlane"}


@router.get("/{role}/{vs_hero_id}", response_model=list[MatchupAdvantageOut])
def get_matchup_advantage(
    role: str, vs_hero_id: int, conn: psycopg.Connection = Depends(get_conn)
) -> list[MatchupAdvantageOut]:
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"role must be one of {sorted(VALID_ROLES)}")

    rows = conn.execute(
        """
        SELECT a.hero_id, h.localized_name, a.vs_hero_id, a.wr_a_b, a.hero_wr,
               a.vs_hero_wr, a.xwr_a_b, a.advantage, a.rank_vs_hero
        FROM hero_matchup_advantage a
        JOIN heroes h ON h.id = a.hero_id
        WHERE a.role_name = %s AND a.vs_hero_id = %s
        ORDER BY a.rank_vs_hero
        """,
        (role, vs_hero_id),
    ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No matchup data for this role/opponent")

    return [
        MatchupAdvantageOut(
            hero_id=r[0],
            hero_name=r[1],
            vs_hero_id=r[2],
            wr_a_b=r[3],
            hero_wr=r[4],
            vs_hero_wr=r[5],
            xwr_a_b=r[6],
            advantage=r[7],
            rank_vs_hero=r[8],
        )
        for r in rows
    ]
