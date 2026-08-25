from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.db import pool
from app.api.routers import analysis, coach, draft, heroes, matchup, players
from app.engine.coach import ensure_coach_plans_table, ensure_rate_limit_table


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool.open()
    with pool.connection() as conn:
        ensure_coach_plans_table(conn)
        ensure_rate_limit_table(conn)
    yield
    pool.close()


app = FastAPI(title="Dota2 Hero Picking API", lifespan=lifespan)

_allowed_origins = os.environ.get("ALLOWED_ORIGINS")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins.split(",") if _allowed_origins else ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(heroes.router)
app.include_router(matchup.router)
app.include_router(draft.router)
app.include_router(players.router)
app.include_router(analysis.router)
app.include_router(coach.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
