"""Phase 2 step 4: list players with pulled history, for the personal-history selector.

Only public players are returned — private ones have no player_hero_stats
rows (see docs/players_id.txt / load_players.py), so they'd be useless in a
picker.
"""
from fastapi import APIRouter, Depends
import psycopg

from app.api.db import get_conn
from app.api.schemas.player import PlayerOut

router = APIRouter(prefix="/players", tags=["players"])


@router.get("", response_model=list[PlayerOut])
def list_players(conn: psycopg.Connection = Depends(get_conn)) -> list[PlayerOut]:
    rows = conn.execute(
        "SELECT account_id, player_name FROM players WHERE is_public ORDER BY player_name"
    ).fetchall()
    return [PlayerOut(account_id=account_id, name=name) for account_id, name in rows]
