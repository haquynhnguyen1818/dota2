"""LLM synthesis for the post-draft coach. Phase G of docs/coaching_plan.md.

Turns the deterministic `DraftContext` (draft_context.py) into a short
natural-language plan with one Claude call. No new signals are computed here --
every *number* the model states must already exist in the context JSON; general
Dota knowledge (item choices, ability interactions, how a strategy plays out)
is fine, a number recalled or invented from outside the context is not.

No patch data is supplied. General hero/item knowledge is stable enough that
the model doesn't need pinning to a version, and the only thing patch notes
would add -- specific numeric tuning -- is exactly what the context-only rule
forbids the model from citing anyway.
"""
from dataclasses import asdict
from datetime import timedelta
from hashlib import sha256
import json

import anthropic
from pydantic import BaseModel
import psycopg
from psycopg.types.json import Jsonb

from app.engine.draft_context import DraftContext, bucket_label

MODEL = "claude-sonnet-5"
# The JSON output itself is short, but Sonnet 5's adaptive thinking (on by
# default) draws from this same budget, and non-English prose runs longer per
# sentence -- 2000 truncated mid-field on a real Vietnamese response and threw
# a JSON parse error. Generous headroom is a fraction of a cent either way.
MAX_TOKENS = 4096

DEFAULT_LANGUAGE = "en"
LANGUAGE_DIRECTIVES = {
    "en": "Write your entire response in English.",
    "vi": (
        "Write your entire response in Vietnamese (Tiếng Việt). Hero, item, and "
        "ability names may stay in their common English/Dota 2 form, since that's "
        "how players actually refer to them, but every sentence of advice must be "
        "in Vietnamese."
    ),
}
LANGUAGES = set(LANGUAGE_DIRECTIVES)

# Rate limit: RATE_LIMIT real Claude calls per RATE_WINDOW_MINUTES, rolling.
# A correct PIN adds UNLOCK_BONUS more, logged as its own event in the same
# window -- so the bonus ages out along with everything else after
# RATE_WINDOW_MINUTES, rather than ratcheting the effective limit up forever.
RATE_LIMIT = 5
RATE_WINDOW_MINUTES = 45
UNLOCK_BONUS = 5


class LaneAdvice(BaseModel):
    instruction: str
    first_item: str
    risk: str


class ClockAdvice(BaseModel):
    your_window: str
    their_spike: str


class DetailAdvice(BaseModel):
    early: str
    mid: str
    late: str


class CoachPlan(BaseModel):
    frame: str
    lane: LaneAdvice
    clock: ClockAdvice
    wincon: str
    detail: DetailAdvice


SYSTEM_PROMPT = """You are a Dota 2 coach speaking to a player whose draft just \
finished. You are given a JSON context object holding every number you are \
allowed to use: a power curve (win rate by game-length bucket), a predicted \
lane matchup, enemy item timings, and each team's capability-tag counts.

Central rule: every number in your output -- a percentage, a minute, a delta \
-- must come from that JSON. If a timing or win rate is not in the input, do \
not state one. You may freely use general Dota 2 knowledge (hero abilities, \
item choices, how a strategy plays out) for qualitative advice; you may not \
invent or recall a *number* from outside the supplied context.

`enemy_item_timings` may hold up to three items per enemy hero. Do not list \
them all -- cite at most one or two, whichever are most relevant to this \
specific matchup, inside `clock.their_spike`.

Never call the power curve a "win chance" or "win probability" -- it is a \
heuristic average of individual hero win rates, not a team win prediction. \
Call it a "power curve" or describe the trend in words.

Never quote a JSON field name from the context (e.g. `tempo_verdict`, \
`crossover_point`, `matchup_delta`) in your prose. Those are internal labels, \
not phrases a player would say -- describe what they mean in plain language \
instead.

Keep `frame` and `wincon` to one sentence each. Keep every other field to one \
or two sentences."""


def cache_key(
    my_hero_id: int,
    my_role: str | None,
    ally_picks: list[int],
    enemy_picks: list[int],
    language: str = DEFAULT_LANGUAGE,
) -> str:
    """Stable key for repeat views of the same draft.

    Sorts each team's own picks separately, not all ten together -- collapsing
    both teams into one sorted set would hash "ally X vs enemy Y" the same as
    "ally Y vs enemy X", which is the opposite matchup with a different frame
    and wincon. `language` is part of the key too -- the plan text itself
    differs by language, so an English and a Vietnamese request for the same
    draft must never collide on the same cache row.
    """
    payload = {
        "my_hero_id": my_hero_id,
        "my_role": my_role,
        "ally_picks": sorted(ally_picks),
        "enemy_picks": sorted(enemy_picks),
        "language": language,
    }
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def build_prompt(
    context: DraftContext, names: dict[int, str], ally_picks: list[int], enemy_picks: list[int]
) -> str:
    """Everything the model may read, human-readable. Pure -- no I/O."""
    payload = {
        "my_hero": names[context.my_hero_id],
        "my_role": context.my_role,
        "ally_heroes": [names[h] for h in ally_picks],
        "enemy_heroes": [names[h] for h in enemy_picks],
        "power_curve": [asdict(p) for p in context.power_curve],
        "crossover_point": bucket_label(context.crossover_bucket) if context.crossover_bucket is not None else None,
        "tempo_verdict": context.tempo_verdict,
        "predicted_lane": asdict(context.predicted_lane),
        "enemy_item_timings": [asdict(c) for c in context.enemy_clocks],
        "my_team_capabilities": context.my_comp,
        "enemy_team_capabilities": context.their_comp,
    }
    return json.dumps(payload, indent=2)


def generate_plan(client: anthropic.Anthropic, prompt: str, language: str = DEFAULT_LANGUAGE) -> CoachPlan:
    system = f"{SYSTEM_PROMPT}\n\n{LANGUAGE_DIRECTIVES[language]}"
    response = client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_format=CoachPlan,
    )
    return response.parsed_output


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

CREATE_COACH_PLANS_TABLE = """
CREATE TABLE IF NOT EXISTS coach_plans (
    cache_key  TEXT PRIMARY KEY,
    plan       JSONB NOT NULL,
    model      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def ensure_coach_plans_table(conn: psycopg.Connection) -> None:
    conn.execute(CREATE_COACH_PLANS_TABLE)
    conn.commit()


def load_cached_plan(conn: psycopg.Connection, key: str) -> CoachPlan | None:
    row = conn.execute("SELECT plan FROM coach_plans WHERE cache_key = %s", (key,)).fetchone()
    return CoachPlan.model_validate(row[0]) if row else None


def store_plan(conn: psycopg.Connection, key: str, plan: CoachPlan) -> None:
    conn.execute(
        "INSERT INTO coach_plans (cache_key, plan, model) VALUES (%s, %s, %s) "
        "ON CONFLICT (cache_key) DO NOTHING",
        (key, Jsonb(plan.model_dump()), MODEL),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Rate limit
# --------------------------------------------------------------------------
#
# One shared budget across every caller -- there's no per-user concept
# anywhere in this API. Only a real Claude call (a cache miss) should ever
# call `record_call`; cache hits are free and must not touch this table.

CREATE_RATE_LIMIT_TABLE = """
CREATE TABLE IF NOT EXISTS coach_rate_limit_events (
    id         BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('call', 'unlock')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

RATE_LIMIT_COUNTS_QUERY = """
SELECT count(*) FILTER (WHERE event_type = 'call'),
       count(*) FILTER (WHERE event_type = 'unlock')
FROM coach_rate_limit_events
WHERE created_at > now() - %s
"""


def ensure_rate_limit_table(conn: psycopg.Connection) -> None:
    conn.execute(CREATE_RATE_LIMIT_TABLE)
    conn.commit()


def effective_limit(unlocks: int) -> int:
    """How many calls are allowed in the current window, given how many times
    the PIN has been entered within that same window."""
    return RATE_LIMIT + UNLOCK_BONUS * unlocks


def is_rate_limited(calls: int, unlocks: int) -> bool:
    return calls >= effective_limit(unlocks)


def load_rate_limit_counts(conn: psycopg.Connection) -> tuple[int, int]:
    """(calls, unlocks) in the last RATE_WINDOW_MINUTES. Pass through
    `is_rate_limited` / `effective_limit` for the actual decision."""
    calls, unlocks = conn.execute(
        RATE_LIMIT_COUNTS_QUERY, (timedelta(minutes=RATE_WINDOW_MINUTES),)
    ).fetchone()
    return int(calls), int(unlocks)


def record_call(conn: psycopg.Connection) -> None:
    """Log one real Claude call. Call only after `generate_plan` succeeds --
    a failed call shouldn't burn the caller's quota."""
    conn.execute("INSERT INTO coach_rate_limit_events (event_type) VALUES ('call')")
    conn.commit()


def record_unlock(conn: psycopg.Connection) -> None:
    conn.execute("INSERT INTO coach_rate_limit_events (event_type) VALUES ('unlock')")
    conn.commit()
