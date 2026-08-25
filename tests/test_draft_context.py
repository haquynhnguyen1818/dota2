"""Tests for the post-draft power curve (engine/draft_context.py).

`build_context` is pure, so everything here runs on synthetic stats with no DB.
"""
import pytest

from app.engine.draft_context import (
    CHART_BUCKETS,
    BucketStats,
    build_context,
    bucket_label,
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
    return build_context(MY_HERO, "Carry", ALLIES, ENEMIES, stats_from(ally_rates | enemy_rates))


def test_win_rate_is_the_team_mean_not_the_sum():
    ctx = context(flat(ALLIES, 0.60), flat(ENEMIES, 0.40))
    assert ctx.power_curve[0].my_win_rate == pytest.approx(0.60)
    assert ctx.power_curve[0].their_win_rate == pytest.approx(0.40)
    assert ctx.power_curve[0].delta == pytest.approx(0.20)


def test_curve_covers_every_charted_bucket():
    ctx = context(flat(ALLIES, 0.5), flat(ENEMIES, 0.5))
    assert [p.bucket for p in ctx.power_curve] == list(CHART_BUCKETS)


def test_no_crossover_when_one_team_leads_throughout():
    ctx = context(flat(ALLIES, 0.55), flat(ENEMIES, 0.45))
    assert ctx.crossover_bucket is None


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
    ctx = context(flat(ALLIES, 0.55), flat(ENEMIES, 0.45))
    assert ctx.tempo_verdict == "even"


def test_bucket_missing_for_one_hero_drops_that_bucket_only():
    ally_rates = flat(ALLIES, 0.55)
    del ally_rates[3][7]
    ctx = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, stats_from(ally_rates | flat(ENEMIES, 0.45)))
    buckets = [p.bucket for p in ctx.power_curve]
    assert 7 not in buckets
    assert buckets == [b for b in CHART_BUCKETS if b != 7]


def test_zero_games_is_treated_as_missing_data():
    stats = stats_from(flat(ALLIES, 0.55) | flat(ENEMIES, 0.45))
    stats[3][7] = (0, 0)
    ctx = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, stats)
    assert 7 not in [p.bucket for p in ctx.power_curve]


def test_hero_absent_entirely_yields_empty_curve_and_unknown_tempo():
    stats = stats_from(flat(ALLIES[1:], 0.55) | flat(ENEMIES, 0.45))
    ctx = build_context(MY_HERO, "Carry", ALLIES, ENEMIES, stats)
    assert ctx.power_curve == []
    assert ctx.crossover_bucket is None
    assert ctx.tempo_verdict == "unknown"


@pytest.mark.parametrize(
    "allies, enemies",
    [
        ([1, 2, 3, 4], ENEMIES),
        (ALLIES, [6, 7, 8, 9]),
        ([1, 2, 3, 4, 5, 6], ENEMIES),
    ],
)
def test_teams_must_hold_five_heroes(allies, enemies):
    with pytest.raises(ValueError, match="5 hero ids"):
        build_context(MY_HERO, "Carry", allies, enemies, {})


def test_my_hero_must_be_an_ally():
    with pytest.raises(ValueError, match="my_hero_id"):
        build_context(99, "Carry", ALLIES, ENEMIES, {})


def test_role_is_optional_and_carried_through_untouched():
    stats = stats_from(flat(ALLIES, 0.55) | flat(ENEMIES, 0.45))
    without = build_context(MY_HERO, None, ALLIES, ENEMIES, stats)
    with_role = build_context(MY_HERO, "Midlane", ALLIES, ENEMIES, stats)
    assert without.my_role is None
    assert with_role.my_role == "Midlane"
    # Role is context for the LLM phase only -- it must not touch the curve.
    assert without.power_curve == with_role.power_curve
    assert without.crossover_bucket == with_role.crossover_bucket
    assert without.tempo_verdict == with_role.tempo_verdict


def test_bucket_labels_follow_the_five_minute_mapping():
    assert bucket_label(3) == "15-20"
    assert bucket_label(7) == "35-40"
    assert bucket_label(13) == "65-70"
