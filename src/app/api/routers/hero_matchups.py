"""One hero's own win rate and its edge against every other hero.

The transpose of `/matchup-advantage/{role}/{vs_hero_id}`. That endpoint fixes an
opponent and ranks a role list against it; this one fixes a hero and ranks all
126 opponents. Both read the same `hero_matchup_advantage` rows -- no new
computation, and `compute_hero_matchup_advantage.py` is untouched.

**Why `DISTINCT ON` rather than a role filter.** The table's primary key is
(role_name, hero_id, vs_hero_id), so a hero in several role lists has one row per
list for the same opponent. Only `rank_vs_hero` is role-scoped: `advantage`,
`wr_a_b`, `hero_wr` and `vs_hero_wr` are computed from the pair alone, with no
role term. Verified on production rather than assumed -- of all (hero_id,
vs_hero_id) pairs, zero have more than one distinct `advantage`. So collapsing
duplicates is lossless, and this view needs no role input at all.

`rank_vs_hero` is deliberately not returned: it ranks a role list against a fixed
opponent, which is the wrong axis here and would read as "this hero's rank"
when it is nothing of the kind.
"""
from fastapi import APIRouter, Depends, HTTPException
import psycopg

from app.api.db import get_conn
from app.api.schemas.hero_matchups import HeroMatchupOut, HeroMatchupsOut

router = APIRouter(prefix="/hero-matchups", tags=["hero-matchups"])

MATCHUPS_SQL = """
SELECT vs_hero_id, vs_hero_name, wr_a_b, vs_hero_wr, advantage, hero_wr
FROM (
    SELECT DISTINCT ON (a.vs_hero_id)
           a.vs_hero_id,
           h.localized_name AS vs_hero_name,
           a.wr_a_b,
           a.vs_hero_wr,
           a.advantage,
           a.hero_wr
    FROM hero_matchup_advantage a
    JOIN heroes h ON h.id = a.vs_hero_id
    WHERE a.hero_id = %s
    ORDER BY a.vs_hero_id, a.role_name
) deduped
ORDER BY advantage DESC
"""


@router.get("/{hero_id}", response_model=HeroMatchupsOut)
def get_hero_matchups(
    hero_id: int, conn: psycopg.Connection = Depends(get_conn)
) -> HeroMatchupsOut:
    name = conn.execute(
        "SELECT localized_name FROM heroes WHERE id = %s", (hero_id,)
    ).fetchone()
    if name is None:
        raise HTTPException(status_code=404, detail="Unknown hero id")

    rows = conn.execute(MATCHUPS_SQL, (hero_id,)).fetchall()
    if not rows:
        # Reachable only if the hero is in no role list at all, since
        # hero_matchup_advantage is built from the role sheet.
        raise HTTPException(status_code=404, detail="No matchup data for this hero")

    return HeroMatchupsOut(
        hero_id=hero_id,
        hero_name=name[0],
        hero_wr=rows[0][5],
        matchups=[
            HeroMatchupOut(
                vs_hero_id=r[0],
                vs_hero_name=r[1],
                wr_a_b=r[2],
                vs_hero_wr=r[3],
                advantage=r[4],
            )
            for r in rows
        ],
    )
