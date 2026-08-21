from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.db import pool
from app.api.routers import draft, heroes, matchup


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    pool.open()
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
