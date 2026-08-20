from fastapi import FastAPI

from app.api.routers import draft, heroes, matchup

app = FastAPI(title="Dota2 Hero Picking API")

app.include_router(heroes.router)
app.include_router(matchup.router)
app.include_router(draft.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
