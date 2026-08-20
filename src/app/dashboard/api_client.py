"""Thin HTTP wrapper around the FastAPI service (src/app/api/)."""
import os

import requests

API_BASE_URL = os.environ.get("DOTA2_API_BASE_URL", "http://127.0.0.1:8000")


def get_heroes() -> list[dict]:
    r = requests.get(f"{API_BASE_URL}/heroes", timeout=10)
    r.raise_for_status()
    return r.json()


def get_matchup_advantage(role: str, vs_hero_id: int) -> list[dict]:
    r = requests.get(f"{API_BASE_URL}/matchup-advantage/{role}/{vs_hero_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def get_draft_suggestions(opponent_picks: list[int]) -> dict:
    r = requests.post(
        f"{API_BASE_URL}/draft-suggestions",
        json={"opponent_picks": opponent_picks},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()
