"""Fetch laning-phase outcomes per hero pair from Stratz and load them into Postgres.

This is the **only** laning-phase win/loss data in the schema. Everything else
that looks like a lane statistic is not one:

  * `stratz_hero_matchups` is a *whole-match* pair win rate. It is what
    `engine/draft_context.py` currently derives `predicted_lane.matchup_delta`
    from, which is why that field reports how four heroes' whole games go rather
    than how their lane goes.
  * `stratz_hero_positions.wins` is the whole-game win rate of games in which a
    hero played a given position -- not whether the lane was won.

Both directions are loaded, keyed by `is_with`:

  * `is_with = false` -- lane *opponents*. This is what replaces the whole-game
    stand-in behind `matchup_delta`.
  * `is_with = true`  -- lane *partner*. The lane-specific synergy split
    deferred in proj_obj.txt Phase 2 step 2, note (b).

Summed over the latest 2 weeks and stored without a `week` column, matching
`stratz_hero_matchups` and `stratz_hero_synergy` -- the rolling 2-week window is
a locked decision (docs/coaching_plan.md).

Schema verified 2026-10-06 against the generated models at
github.com/TheAmazingLooser/STRATZ_Models (`HeroLaneOutcomeType.cs`,
`HeroStatsQueryQueryBuilder.WithLaneOutcome`), because the Stratz token is bound
to the Droplet's IP and could not be introspected from a laptop. Three things
that reading those models corrected, all of which would have shipped as bugs:

  * **`laneOutcome` takes no `take` argument.** Its full argument list is
    `isWith` (required), `heroId`, `week`, `bracketBasicIds`, `positionIds`.
    Passing `take` the way the sibling `matchUp` loaders do is a hard error.
  * **Lanes draw.** The type carries `drawCount` alongside `winCount`/
    `lossCount`, so a lane win rate computed as `wins / (wins + losses)` is not
    the same number as `wins / matchCount`. Both are stored; pick deliberately.
  * **`winCount` and `matchWinCount` are different questions** -- won the lane
    versus won the game. Storing both is what makes "wins lane, loses game"
    checkable in-table rather than an assumption, which is the whole reason this
    table exists. The columns are named `lane_*` and `match_wins` so a consumer
    cannot reach for the wrong one by accident.

`heroId` is optional on this endpoint -- omitting it returns every hero at once,
which is exactly the ~1MB+ response Stratz truncates mid-stream (see
docs/progress.md). It is not a list either, so batching like
`load_stratz_matchups.py` is not available: one request per hero, as
`load_stratz_item_timings.py` does.

`positionIds` is not passed, so the endpoint reports every position it has and
`position` comes back on each row. It is stored and part of the primary key,
since the coach's lane logic is position-aware (pos 1+5 safelane, 2 mid, 3+4
offlane). A null position is stored as 'ALL' -- Postgres forbids NULL in a
primary key, and this way the loader survives the endpoint returning ungrouped
rows instead of failing on insert.
"""
import time
from collections import defaultdict
from typing import Any

import psycopg
import requests

from app.credentials import db_kwargs, stratz_headers

STRATZ_URL = "https://api.stratz.com/graphql"

RECENT_WEEKS = 2

# 127 heroes x 2 weeks x 2 directions = 508 requests. Same throttle as
# load_stratz_item_timings.py, which measured ~78 requests/minute against a
# 150/minute limit once latency is counted. Well inside the 1500/hour ceiling.
REQUEST_DELAY = 0.3

# No `take` argument exists on this field -- see the module docstring.
LANE_QUERY = """
query ($heroId: Short!, $week: Long, $isWith: Boolean!) {
  heroStats {
    laneOutcome(heroId: $heroId, week: $week, isWith: $isWith) {
      heroId2
      position
      matchCount
      winCount
      drawCount
      lossCount
      matchWinCount
    }
  }
}
"""

CREATE_LANE_TABLE = """
CREATE TABLE IF NOT EXISTS stratz_hero_lane_outcome (
    hero_id INTEGER REFERENCES heroes(id),
    other_hero_id INTEGER REFERENCES heroes(id),
    is_with BOOLEAN,
    position TEXT,
    games_played BIGINT,
    lane_wins BIGINT,
    lane_draws BIGINT,
    lane_losses BIGINT,
    match_wins BIGINT,
    PRIMARY KEY (hero_id, other_hero_id, is_with, position)
)
"""

UPSERT_LANE = """
INSERT INTO stratz_hero_lane_outcome
    (hero_id, other_hero_id, is_with, position,
     games_played, lane_wins, lane_draws, lane_losses, match_wins)
VALUES
    (%(hero_id)s, %(other_hero_id)s, %(is_with)s, %(position)s,
     %(games_played)s, %(lane_wins)s, %(lane_draws)s, %(lane_losses)s, %(match_wins)s)
ON CONFLICT (hero_id, other_hero_id, is_with, position) DO UPDATE SET
    games_played = EXCLUDED.games_played,
    lane_wins = EXCLUDED.lane_wins,
    lane_draws = EXCLUDED.lane_draws,
    lane_losses = EXCLUDED.lane_losses,
    match_wins = EXCLUDED.match_wins
"""

_COUNTS = ("games_played", "lane_wins", "lane_draws", "lane_losses", "match_wins")


def _fetch(hero_id: int, week: int, is_with: bool) -> list[dict[str, Any]]:
    """One hero, one week, one direction. Raises the GraphQL error verbatim."""
    response = requests.post(
        STRATZ_URL,
        json={
            "query": LANE_QUERY,
            "variables": {"heroId": hero_id, "week": week, "isWith": is_with},
        },
        headers=stratz_headers(),
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])

    return data["data"]["heroStats"]["laneOutcome"] or []


def fetch_lane_outcomes(hero_ids: list[int], weeks: list[int]) -> list[dict[str, Any]]:
    """Every hero x week x direction, summed across weeks into one row per pair+position."""
    totals: dict[tuple[int, int, bool, str], dict[str, int]] = defaultdict(
        lambda: dict.fromkeys(_COUNTS, 0)
    )

    for week in weeks:
        for is_with in (False, True):
            for hero_id in hero_ids:
                for row in _fetch(hero_id, week, is_with):
                    # Nulls are possible on every count; a missing count is 0, not a crash.
                    key = (hero_id, row["heroId2"], is_with, row["position"] or "ALL")
                    bucket = totals[key]
                    bucket["games_played"] += row["matchCount"] or 0
                    bucket["lane_wins"] += row["winCount"] or 0
                    bucket["lane_draws"] += row["drawCount"] or 0
                    bucket["lane_losses"] += row["lossCount"] or 0
                    bucket["match_wins"] += row["matchWinCount"] or 0
                time.sleep(REQUEST_DELAY)

    return [
        {
            "hero_id": hero_id,
            "other_hero_id": other_hero_id,
            "is_with": is_with,
            "position": position,
            **counts,
        }
        for (hero_id, other_hero_id, is_with, position), counts in totals.items()
    ]


def main() -> None:
    with psycopg.connect(**db_kwargs()) as conn:
        hero_ids = [r[0] for r in conn.execute("SELECT id FROM heroes ORDER BY id").fetchall()]
        weeks = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT week FROM stratz_hero_win_week ORDER BY week DESC LIMIT {RECENT_WEEKS}"
            ).fetchall()
        ]

        rows = fetch_lane_outcomes(hero_ids, weeks)

        with conn.cursor() as cur:
            cur.execute(CREATE_LANE_TABLE)
            cur.executemany(UPSERT_LANE, rows)
        conn.commit()

    vs_rows = sum(1 for r in rows if not r["is_with"])
    print(
        f"Loaded {len(rows)} stratz_hero_lane_outcome rows "
        f"({vs_rows} vs / {len(rows) - vs_rows} with, summed over weeks {weeks}) "
        f"into '{db_kwargs()['dbname']}'."
    )


if __name__ == "__main__":
    main()
