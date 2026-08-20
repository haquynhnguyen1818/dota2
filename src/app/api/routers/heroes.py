from fastapi import APIRouter, Depends
import psycopg

from app.api.db import get_conn
from app.api.schemas.hero import HeroOut

router = APIRouter(prefix="/heroes", tags=["heroes"])


@router.get("", response_model=list[HeroOut])
def list_heroes(conn: psycopg.Connection = Depends(get_conn)) -> list[HeroOut]:
    rows = conn.execute("SELECT id, localized_name FROM heroes ORDER BY localized_name").fetchall()
    return [HeroOut(id=hero_id, name=name) for hero_id, name in rows]
