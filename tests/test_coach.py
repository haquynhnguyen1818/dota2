"""Tests for the LLM synthesis layer (engine/coach.py).

`cache_key` and `build_prompt` are pure -- no DB, no network. `generate_plan`
is exercised against a stub client so the request/response shape is checked
without a real API call.
"""
from types import SimpleNamespace

from app.engine.coach import (
    LANGUAGE_DIRECTIVES,
    RATE_LIMIT,
    UNLOCK_BONUS,
    CoachPlan,
    build_prompt,
    cache_key,
    effective_limit,
    generate_plan,
    is_rate_limited,
)
from app.engine.draft_context import ContextData, build_context

ALLIES = [1, 2, 3, 4, 5]
ENEMIES = [6, 7, 8, 9, 10]
MY_HERO = 1

NAMES = {i: f"Hero{i}" for i in range(1, 11)}

PLAN = CoachPlan(
    frame="You win long, they must force fights early.",
    lane={"instruction": "Play for tempo.", "first_item": "Magic Wand", "risk": "Ganks from mid."},
    clock={"your_window": "25-35 minutes.", "their_spike": "Watch for their level 6 combo."},
    wincon="Group and take towers once ahead.",
    detail={"early": "Farm safely.", "mid": "Look for picks.", "late": "Close it out."},
)


# --------------------------------------------------------------------------
# cache_key
# --------------------------------------------------------------------------

def test_cache_key_is_stable_regardless_of_pick_order():
    a = cache_key(MY_HERO, "Carry", [5, 4, 3, 2, 1], [10, 9, 8, 7, 6])
    b = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES)
    assert a == b


def test_cache_key_differs_when_the_two_teams_are_swapped():
    # Swapping which team is "ally" and which is "enemy" is a different draft
    # -- a different frame and wincon -- even though the set of ten heroes is
    # identical. Sorting all ten ids together instead of per-team would
    # collapse these into the same key.
    swapped_my_hero = 6
    a = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES)
    b = cache_key(swapped_my_hero, "Carry", ENEMIES, ALLIES)
    assert a != b


def test_cache_key_differs_on_role():
    a = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES)
    b = cache_key(MY_HERO, "Midlane", ALLIES, ENEMIES)
    assert a != b


def test_cache_key_differs_on_language():
    # An English and a Vietnamese plan for the same draft are different text --
    # they must never share a cache row.
    a = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES, language="en")
    b = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES, language="vi")
    assert a != b


def test_cache_key_defaults_to_english():
    a = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES)
    b = cache_key(MY_HERO, "Carry", ALLIES, ENEMIES, language="en")
    assert a == b


def test_cache_key_differs_on_my_hero():
    a = cache_key(1, "Carry", ALLIES, ENEMIES)
    b = cache_key(2, "Carry", ALLIES, ENEMIES)
    assert a != b


# --------------------------------------------------------------------------
# build_prompt
# --------------------------------------------------------------------------

def test_prompt_uses_hero_names_not_raw_ids():
    context = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, ContextData())
    prompt = build_prompt(context, NAMES, ALLIES, ENEMIES)
    assert "Hero1" in prompt
    assert "Hero10" in prompt


def test_prompt_carries_no_patch_data():
    # Phase G explicitly dropped the patch blob -- nothing patch-shaped should
    # sneak into the prompt via a stray field.
    context = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, ContextData())
    prompt = build_prompt(context, NAMES, ALLIES, ENEMIES)
    assert "patch" not in prompt.lower()


def test_prompt_omits_crossover_point_when_there_is_none():
    context = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, ContextData())
    prompt = build_prompt(context, NAMES, ALLIES, ENEMIES)
    assert '"crossover_point": null' in prompt


# --------------------------------------------------------------------------
# generate_plan
# --------------------------------------------------------------------------

class _StubMessages:
    def __init__(self, plan: CoachPlan):
        self._plan = plan
        self.received_kwargs: dict | None = None

    def parse(self, **kwargs):
        self.received_kwargs = kwargs
        return SimpleNamespace(parsed_output=self._plan)


class _StubClient:
    def __init__(self, plan: CoachPlan):
        self.messages = _StubMessages(plan)


def test_generate_plan_returns_the_parsed_output():
    client = _StubClient(PLAN)
    assert generate_plan(client, "context json here") == PLAN


def test_generate_plan_requests_structured_output():
    client = _StubClient(PLAN)
    generate_plan(client, "context json here")
    kwargs = client.messages.received_kwargs
    assert kwargs["output_format"] is CoachPlan
    assert kwargs["messages"] == [{"role": "user", "content": "context json here"}]


def test_generate_plan_defaults_to_the_english_directive():
    client = _StubClient(PLAN)
    generate_plan(client, "context json here")
    assert LANGUAGE_DIRECTIVES["en"] in client.messages.received_kwargs["system"]


def test_generate_plan_switches_the_language_directive():
    client = _StubClient(PLAN)
    generate_plan(client, "context json here", language="vi")
    system = client.messages.received_kwargs["system"]
    assert LANGUAGE_DIRECTIVES["vi"] in system
    assert LANGUAGE_DIRECTIVES["en"] not in system


# --------------------------------------------------------------------------
# Rate limit
# --------------------------------------------------------------------------

def test_effective_limit_with_no_unlocks_is_the_base_limit():
    assert effective_limit(0) == RATE_LIMIT


def test_effective_limit_grows_by_the_bonus_per_unlock():
    assert effective_limit(1) == RATE_LIMIT + UNLOCK_BONUS
    assert effective_limit(3) == RATE_LIMIT + 3 * UNLOCK_BONUS


def test_calls_under_the_limit_are_allowed():
    assert not is_rate_limited(calls=RATE_LIMIT - 1, unlocks=0)


def test_calls_at_the_limit_are_blocked():
    assert is_rate_limited(calls=RATE_LIMIT, unlocks=0)


def test_an_unlock_raises_the_ceiling_by_the_bonus():
    # The 6th call is blocked with no unlock...
    assert is_rate_limited(calls=RATE_LIMIT, unlocks=0)
    # ...but allowed once a single unlock has been logged in the same window.
    assert not is_rate_limited(calls=RATE_LIMIT, unlocks=1)


def test_a_second_unlock_in_the_same_window_stacks():
    at_first_unlock_ceiling = RATE_LIMIT + UNLOCK_BONUS
    assert is_rate_limited(calls=at_first_unlock_ceiling, unlocks=1)
    assert not is_rate_limited(calls=at_first_unlock_ceiling, unlocks=2)
