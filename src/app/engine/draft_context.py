"""Deterministic post-draft context: the power curve for a completed 5v5.

Phase B1 of docs/coaching_plan.md. No LLM, no DB — `build_context` is a pure
function over hero duration stats so it can be unit-tested directly. Loading
those stats is `load_bucket_stats`'s job, kept separate for that reason.

**The power curve is a heuristic, not a win probability.** It averages each
team's five heroes' individual win rates at a given game length; hero
interaction effects are not in it at all (those live in `stratz_hero_matchups`
and `stratz_hero_synergy`). Label it "power curve" in any UI, never "win
chance".
"""
from dataclasses import dataclass

import psycopg

# Buckets 3-13 = 15-70 min = 98.3% of games. Buckets 0/1/2 and 14 are excluded
# deliberately: bucket 1 has zero rows anywhere, bucket 0 holds more games than
# bucket 2 despite supposedly being shorter, so the low end reads as a catch-all
# rather than real duration bins. See docs/progress.md.
FIRST_BUCKET = 3
LAST_BUCKET = 13
CHART_BUCKETS = range(FIRST_BUCKET, LAST_BUCKET + 1)

BUCKET_WIDTH_MINUTES = 5

# Buckets compared to decide whether you want the game short or long.
EARLY_BUCKETS = range(3, 7)   # 15-35 min
LATE_BUCKETS = range(10, 14)  # 50-70 min

# Minimum early-vs-late gap, in win-rate fraction, before calling a tempo.
# 0.005 = half a percentage point.
TEMPO_EPSILON = 0.005

TEAM_SIZE = 5

# hero_id -> bucket -> (wins, games_played), already rolled up to the window.
BucketStats = dict[int, dict[int, tuple[int, int]]]


def bucket_label(bucket: int) -> str:
    return f"{bucket * BUCKET_WIDTH_MINUTES}-{(bucket + 1) * BUCKET_WIDTH_MINUTES}"


@dataclass(frozen=True)
class CurvePoint:
    bucket: int
    minutes: str
    my_win_rate: float
    their_win_rate: float
    delta: float


@dataclass(frozen=True)
class DraftContext:
    my_hero_id: int
    my_role: str
    power_curve: list[CurvePoint]
    crossover_bucket: int | None
    tempo_verdict: str


def _team_win_rate(team: list[int], bucket: int, stats: BucketStats) -> float | None:
    """Mean of the team's per-hero win rates in this bucket, or None if any hero lacks data.

    Mean rather than sum: summing five win rates gives a number near 250% that
    means nothing. Requiring all five keeps the two teams comparable.
    """
    rates = []
    for hero_id in team:
        entry = stats.get(hero_id, {}).get(bucket)
        if entry is None:
            return None
        wins, games_played = entry
        if games_played == 0:
            return None
        rates.append(wins / games_played)
    return sum(rates) / len(rates)


def _crossover(curve: list[CurvePoint]) -> int | None:
    """First bucket whose delta is no longer on the side of zero the curve started on.

    A delta of exactly 0 counts as the crossing, not as something to skip past —
    otherwise a curve that lands cleanly on 0 and then reverses reports no
    crossover at all. Leading zeros are ignored when establishing which side the
    curve starts on.
    """
    start = next((i for i, p in enumerate(curve) if p.delta != 0), None)
    if start is None:
        return None
    started_positive = curve[start].delta > 0
    for point in curve[start + 1:]:
        if point.delta == 0 or (point.delta > 0) != started_positive:
            return point.bucket
    return None


def _mean_delta(curve: list[CurvePoint], buckets: range) -> float | None:
    deltas = [p.delta for p in curve if p.bucket in buckets]
    return sum(deltas) / len(deltas) if deltas else None


def _tempo_verdict(curve: list[CurvePoint]) -> str:
    early = _mean_delta(curve, EARLY_BUCKETS)
    late = _mean_delta(curve, LATE_BUCKETS)
    if early is None or late is None:
        return "unknown"
    if early - late > TEMPO_EPSILON:
        return "you_are_faster"
    if late - early > TEMPO_EPSILON:
        return "you_win_long"
    return "even"


def build_context(
    my_hero_id: int,
    my_role: str,
    ally_picks: list[int],
    enemy_picks: list[int],
    stats: BucketStats,
) -> DraftContext:
    if len(ally_picks) != TEAM_SIZE or len(enemy_picks) != TEAM_SIZE:
        raise ValueError(f"ally_picks and enemy_picks must each contain {TEAM_SIZE} hero ids")
    if my_hero_id not in ally_picks:
        raise ValueError("my_hero_id must be one of ally_picks")

    curve = []
    for bucket in CHART_BUCKETS:
        mine = _team_win_rate(ally_picks, bucket, stats)
        theirs = _team_win_rate(enemy_picks, bucket, stats)
        if mine is None or theirs is None:
            continue
        curve.append(
            CurvePoint(
                bucket=bucket,
                minutes=bucket_label(bucket),
                my_win_rate=mine,
                their_win_rate=theirs,
                delta=mine - theirs,
            )
        )

    return DraftContext(
        my_hero_id=my_hero_id,
        my_role=my_role,
        power_curve=curve,
        crossover_bucket=_crossover(curve),
        tempo_verdict=_tempo_verdict(curve),
    )


LOAD_BUCKET_STATS = """
WITH recent AS (
    SELECT hero_id, duration_bucket, wins, games_played,
           DENSE_RANK() OVER (ORDER BY week DESC) AS wk
    FROM stratz_hero_duration_wr
)
SELECT hero_id, duration_bucket, SUM(wins), SUM(games_played)
FROM recent
WHERE wk <= %s AND hero_id = ANY(%s)
GROUP BY hero_id, duration_bucket
"""


def load_bucket_stats(conn: psycopg.Connection, hero_ids: list[int], weeks: int = 2) -> BucketStats:
    """Roll `stratz_hero_duration_wr` up to the latest `weeks` weeks.

    DENSE_RANK, not ROW_NUMBER: this table has 14 rows per hero-week, so
    ROW_NUMBER <= 2 would return two duration buckets of a single week. See
    docs/progress.md.
    """
    stats: BucketStats = {}
    for hero_id, bucket, wins, games_played in conn.execute(LOAD_BUCKET_STATS, (weeks, hero_ids)):
        stats.setdefault(hero_id, {})[bucket] = (int(wins), int(games_played))
    return stats
