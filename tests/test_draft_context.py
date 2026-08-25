"""Tests for the post-draft context builder (engine/draft_context.py).

`build_context` is pure, so everything here runs on synthetic data with no DB.
"""
import pytest

from app.engine.draft_context import (
    CHART_BUCKETS,
    POSITIONS,
    TAGS,
    BucketStats,
    ContextData,
    ItemClock,
    assign_positions,
    bucket_label,
    build_context,
)

ALLIES = [1, 2, 3, 4, 5]
ENEMIES = [6, 7, 8, 9, 10]
MY_HERO = 1

GAMES = 10_000


def stats_from(rate_by_hero: dict[int, dict[int, float]]) -> BucketStats:
    return {
        hero_id: {bucket: (round(rate * GAMES), GAMES) for bucket, rate in per_bucket.items()}
        for hero_id, per_bucket in rate_by_hero.items()
    }


def flat(heroes: list[int], rate: float) -> dict[int, dict[int, float]]:
    """Every hero holds the same win rate in every charted bucket."""
    return {h: {b: rate for b in CHART_BUCKETS} for h in heroes}


def sloped(heroes: list[int], start: float, step: float) -> dict[int, dict[int, float]]:
    """Win rate moves by `step` per bucket, starting at `start` in the first bucket."""
    first = min(CHART_BUCKETS)
    return {h: {b: start + step * (b - first) for b in CHART_BUCKETS} for h in heroes}


def context(ally_rates: dict, enemy_rates: dict):
    data = ContextData(buckets=stats_from(ally_rates | enemy_rates))
    return build_context(MY_HERO, "Carry", ALLIES, ENEMIES, data)


# --------------------------------------------------------------------------
# Power curve
# --------------------------------------------------------------------------

def test_win_rate_is_the_team_mean_not_the_sum():
    ctx = context(flat(ALLIES, 0.60), flat(ENEMIES, 0.40))
    assert ctx.power_curve[0].my_win_rate == pytest.approx(0.60)
    assert ctx.power_curve[0].their_win_rate == pytest.approx(0.40)
    assert ctx.power_curve[0].delta == pytest.approx(0.20)


def test_curve_covers_every_charted_bucket():
    ctx = context(flat(ALLIES, 0.5), flat(ENEMIES, 0.5))
    assert [p.bucket for p in ctx.power_curve] == list(CHART_BUCKETS)


def test_no_crossover_when_one_team_leads_throughout():
    assert context(flat(ALLIES, 0.55), flat(ENEMIES, 0.45)).crossover_bucket is None


def test_crossover_when_allies_fade():
    # Allies 0.55 -> 0.45 across buckets 3..13; enemies flat 0.50.
    # Delta hits exactly 0 at bucket 8, which is the crossing.
    ctx = context(sloped(ALLIES, 0.55, -0.01), flat(ENEMIES, 0.50))
    assert ctx.crossover_bucket == 8
    assert ctx.tempo_verdict == "you_are_faster"


def test_crossover_when_allies_scale():
    ctx = context(sloped(ALLIES, 0.45, 0.01), flat(ENEMIES, 0.50))
    assert ctx.crossover_bucket == 8
    assert ctx.tempo_verdict == "you_win_long"


def test_crossover_reported_even_when_delta_never_lands_on_zero():
    # Offset by half a step so the curve steps over zero rather than onto it.
    ctx = context(sloped(ALLIES, 0.555, -0.01), flat(ENEMIES, 0.50))
    assert ctx.crossover_bucket == 9
    assert ctx.power_curve[5].delta > 0  # bucket 8
    assert ctx.power_curve[6].delta < 0  # bucket 9


def test_flat_identical_teams_have_no_crossover_and_even_tempo():
    ctx = context(flat(ALLIES, 0.5), flat(ENEMIES, 0.5))
    assert ctx.crossover_bucket is None
    assert ctx.tempo_verdict == "even"


def test_lead_that_never_reverses_is_even_tempo():
    assert context(flat(ALLIES, 0.55), flat(ENEMIES, 0.45)).tempo_verdict == "even"


def test_bucket_missing_for_one_hero_drops_that_bucket_only():
    ally_rates = flat(ALLIES, 0.55)
    del ally_rates[3][7]
    data = ContextData(buckets=stats_from(ally_rates | flat(ENEMIES, 0.45)))
    ctx = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, data)
    assert [p.bucket for p in ctx.power_curve] == [b for b in CHART_BUCKETS if b != 7]


def test_zero_games_is_treated_as_missing_data():
    stats = stats_from(flat(ALLIES, 0.55) | flat(ENEMIES, 0.45))
    stats[3][7] = (0, 0)
    ctx = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, ContextData(buckets=stats))
    assert 7 not in [p.bucket for p in ctx.power_curve]


def test_hero_absent_entirely_yields_empty_curve_and_unknown_tempo():
    stats = stats_from(flat(ALLIES[1:], 0.55) | flat(ENEMIES, 0.45))
    ctx = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, ContextData(buckets=stats))
    assert ctx.power_curve == []
    assert ctx.crossover_bucket is None
    assert ctx.tempo_verdict == "unknown"


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "allies, enemies",
    [([1, 2, 3, 4], ENEMIES), (ALLIES, [6, 7, 8, 9]), ([1, 2, 3, 4, 5, 6], ENEMIES)],
)
def test_teams_must_hold_five_heroes(allies, enemies):
    with pytest.raises(ValueError, match="5 hero ids"):
        build_context(MY_HERO, "Carry", allies, enemies, ContextData())


def test_my_hero_must_be_an_ally():
    with pytest.raises(ValueError, match="my_hero_id"):
        build_context(99, "Carry", ALLIES, ENEMIES, ContextData())


def test_role_is_optional_and_carried_through_untouched():
    data = ContextData(buckets=stats_from(flat(ALLIES, 0.55) | flat(ENEMIES, 0.45)))
    without = build_context(MY_HERO, None, ALLIES, ENEMIES, data)
    with_role = build_context(MY_HERO, "Midlane", ALLIES, ENEMIES, data)
    assert without.my_role is None and with_role.my_role == "Midlane"
    # Role is context for the LLM phase only -- it must not touch the curve.
    assert without.power_curve == with_role.power_curve
    assert without.tempo_verdict == with_role.tempo_verdict


def test_bucket_labels_follow_the_five_minute_mapping():
    assert bucket_label(3) == "15-20"
    assert bucket_label(7) == "35-40"
    assert bucket_label(13) == "65-70"


# --------------------------------------------------------------------------
# Position assignment
# --------------------------------------------------------------------------

def positions_from(spec: dict[int, dict[str, int]]):
    return spec


def test_positions_are_assigned_by_clear_specialisation():
    spec = {h: {POSITIONS[i]: 100} for i, h in enumerate(ALLIES)}
    assert assign_positions(ALLIES, spec) == {h: POSITIONS[i] for i, h in enumerate(ALLIES)}


def test_every_hero_gets_a_distinct_position():
    # All five want POSITION_1; the assignment must still be a permutation.
    spec = {h: {"POSITION_1": 100, "POSITION_2": 1} for h in ALLIES}
    assigned = assign_positions(ALLIES, spec)
    assert sorted(assigned.values()) == sorted(POSITIONS)


def test_exact_assignment_beats_greedy():
    # Greedy takes hero 1 for POSITION_5 (0.90 > 0.80) and then has to put
    # hero 2 somewhere it barely plays. The exact search prefers the pairing
    # with the higher joint likelihood.
    spec = {
        1: {"POSITION_5": 90, "POSITION_1": 10},
        2: {"POSITION_5": 80, "POSITION_2": 1},
        3: {"POSITION_2": 100}, 4: {"POSITION_3": 100}, 5: {"POSITION_4": 100},
    }
    assigned = assign_positions([1, 2, 3, 4, 5], spec)
    assert assigned[2] == "POSITION_5"
    assert assigned[1] == "POSITION_1"


def test_hero_with_no_position_data_still_gets_a_position():
    spec = {h: {POSITIONS[i]: 100} for i, h in enumerate(ALLIES[:4])}
    assigned = assign_positions(ALLIES, spec)
    assert sorted(assigned.values()) == sorted(POSITIONS)


# --------------------------------------------------------------------------
# Predicted lane
# --------------------------------------------------------------------------

def lane_context(my_hero=MY_HERO, **kwargs):
    # allies 1..5 and enemies 6..10 each specialise into one position
    spec = {h: {POSITIONS[i]: 100} for i, h in enumerate(ALLIES)}
    spec |= {h: {POSITIONS[i]: 100} for i, h in enumerate(ENEMIES)}
    names = {h: f"H{h}" for h in ALLIES + ENEMIES}
    data = ContextData(positions=spec, names=names, **kwargs)
    return build_context(my_hero, None, ALLIES, ENEMIES, data)


def test_safelane_faces_the_enemy_offlane():
    lane = lane_context(my_hero=1).predicted_lane  # hero 1 -> POSITION_1
    assert lane.lane == "safelane"
    assert lane.with_heroes == ["H5"]              # POSITION_5
    assert sorted(lane.vs_heroes) == ["H8", "H9"]  # enemy POSITION_3 / POSITION_4


def test_offlane_faces_the_enemy_safelane():
    lane = lane_context(my_hero=3).predicted_lane  # hero 3 -> POSITION_3
    assert lane.lane == "offlane"
    assert lane.with_heroes == ["H4"]
    assert sorted(lane.vs_heroes) == ["H10", "H6"]


def test_mid_faces_mid_alone():
    lane = lane_context(my_hero=2).predicted_lane
    assert lane.lane == "midlane"
    assert lane.with_heroes == []
    assert lane.vs_heroes == ["H7"]


def test_matchup_delta_is_none_without_matchup_data():
    assert lane_context().predicted_lane.matchup_delta is None


def test_matchup_delta_is_shrunk_toward_zero_on_small_samples():
    # Even win rates and baselines everywhere except one lopsided pair.
    baselines = {h: 0.5 for h in ALLIES + ENEMIES}
    big = {(1, 8): (700, 1000), (1, 9): (500, 1000), (5, 8): (500, 1000), (5, 9): (500, 1000)}
    small = {(1, 8): (7, 10), (1, 9): (5, 10), (5, 8): (5, 10), (5, 9): (5, 10)}
    strong = lane_context(matchups=big, baselines=baselines).predicted_lane.matchup_delta
    weak = lane_context(matchups=small, baselines=baselines).predicted_lane.matchup_delta
    assert strong > weak > 0
    # n=10 against K=500 should shrink almost all the way out
    assert weak < 0.005


# --------------------------------------------------------------------------
# Comp tags and clocks
# --------------------------------------------------------------------------

def test_comp_counts_tags_per_team():
    tags = {h: {t: False for t in TAGS} for h in ALLIES + ENEMIES}
    tags[1]["lockdown"] = tags[2]["lockdown"] = True
    tags[6]["save"] = True
    ctx = build_context(MY_HERO, None, ALLIES, ENEMIES, ContextData(tags=tags))
    assert ctx.my_comp["lockdown"] == 2
    assert ctx.my_comp["save"] == 0
    assert ctx.their_comp["save"] == 1
    assert set(ctx.my_comp) == set(TAGS)


def test_comp_treats_untagged_heroes_as_all_false():
    ctx = build_context(MY_HERO, None, ALLIES, ENEMIES, ContextData())
    assert set(ctx.my_comp.values()) == {0}


def test_enemy_clocks_come_only_from_the_enemy_team():
    clocks = {
        8: [ItemClock(8, "H8", "Manta Style", 22)],
        1: [ItemClock(1, "H1", "Battle Fury", 15)],  # ally, must be ignored
    }
    ctx = build_context(MY_HERO, None, ALLIES, ENEMIES, ContextData(clocks=clocks))
    assert [c.item_name for c in ctx.enemy_clocks] == ["Manta Style"]
