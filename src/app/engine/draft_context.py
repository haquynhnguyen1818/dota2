"""Deterministic post-draft context for a completed 5v5.

Phases B1 and E4 of docs/coaching_plan.md. No LLM. `build_context` is a pure
function over a `ContextData` bundle so it unit-tests without a DB; loading that
bundle is `load_context_data`'s job, kept separate for exactly that reason.

Signals, in the order they were built:
  * `power_curve`  — each team's average win rate by game length (B1)
  * `predicted_lane` — who you lane with and against, and the lane's edge (E4)
  * `enemy_clocks` — when each enemy's key items land (E4)
  * `my_comp` / `their_comp` — capability tag counts per team (E4)

**The power curve is a heuristic, not a win probability.** It averages each
team's five heroes' individual win rates at a given game length; hero
interaction effects are not in it at all (those live in `stratz_hero_matchups`
and `stratz_hero_synergy`). Label it "power curve" in any UI, never "win
chance".

Note the curve's win rates come from the `winWeek` population (via
`stratz_hero_duration_wr`), which is **not** the population behind `hero_wr` in
`/draft-suggestions` — that one is `stratz_hero_matchups`, an
interaction-filtered subset (see `01529a2`). The same hero can therefore read
slightly differently in the two panels; for flex/summon heroes the gap reaches
~4pp. That is expected. `winWeek` is the only source of duration data and is
also the right population for a duration question, being a uniform slice of
all games — pooled across heroes, every bucket sits at exactly 50%.
"""
from dataclasses import dataclass, field
from itertools import permutations
import math

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

POSITIONS = ["POSITION_1", "POSITION_2", "POSITION_3", "POSITION_4", "POSITION_5"]

# Safelane faces the enemy offlane and vice versa; mid faces mid.
LANE_BY_POSITION = {
    "POSITION_1": "safelane", "POSITION_5": "safelane",
    "POSITION_2": "midlane",
    "POSITION_3": "offlane", "POSITION_4": "offlane",
}
OPPOSING_LANE = {"safelane": "offlane", "offlane": "safelane", "midlane": "midlane"}

# Empirical-Bayes shrinkage, same constant and rationale as the draft suggester
# (proj_obj.txt Phase 2 step 2): delta * n/(n+K) pulls small samples toward 0.
SHRINKAGE_K = 500

# Threat items: skip build-up components, skip anything bought in the opening
# minutes, and keep the few a hero actually builds. See progress.md on why
# is_component alone is not enough.
CLOCK_MIN_MINUTE = 10
CLOCKS_PER_HERO = 3

TAGS = ["lockdown", "save", "dispel", "waveclear", "tower_dmg",
        "silence", "break", "cheap_ult", "illusion", "summons"]

# hero_id -> bucket -> (wins, games_played), already rolled up to the window.
BucketStats = dict[int, dict[int, tuple[int, int]]]
# hero_id -> position -> games_played
PositionStats = dict[int, dict[str, int]]
# (hero_id, vs_hero_id) -> (wins, games_played)
MatchupStats = dict[tuple[int, int], tuple[int, int]]


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
class ItemClock:
    hero_id: int
    hero_name: str
    item_name: str
    median_minute: int


@dataclass(frozen=True)
class PredictedLane:
    lane: str | None
    with_heroes: list[str]
    vs_heroes: list[str]
    matchup_delta: float | None


@dataclass(frozen=True)
class ContextData:
    """Everything `build_context` reads. Defaults are empty so a test can supply
    only the slice it cares about."""
    buckets: BucketStats = field(default_factory=dict)
    positions: PositionStats = field(default_factory=dict)
    matchups: MatchupStats = field(default_factory=dict)
    baselines: dict[int, float] = field(default_factory=dict)
    clocks: dict[int, list[ItemClock]] = field(default_factory=dict)
    tags: dict[int, dict[str, bool]] = field(default_factory=dict)
    names: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DraftContext:
    my_hero_id: int
    my_role: str | None
    power_curve: list[CurvePoint]
    crossover_bucket: int | None
    tempo_verdict: str
    predicted_lane: PredictedLane
    enemy_clocks: list[ItemClock]
    my_comp: dict[str, int]
    their_comp: dict[str, int]


# --------------------------------------------------------------------------
# Power curve
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Predicted lane
# --------------------------------------------------------------------------

def assign_positions(team: list[int], positions: PositionStats) -> dict[int, str]:
    """Assign each hero a distinct position by maximum likelihood.

    Brute-forces all 5! = 120 permutations rather than assigning greedily. At
    this size exact is cheaper than being clever, and greedy genuinely errs —
    it will hand POSITION_5 to the hero with the highest pos-5 share even when
    another hero has nowhere else to go.
    """
    if not team:
        return {}
    shares = {}
    for hero_id in team:
        counts = positions.get(hero_id, {})
        total = sum(counts.values())
        shares[hero_id] = {
            p: (counts.get(p, 0) / total if total else 1 / len(POSITIONS)) for p in POSITIONS
        }

    def score(order: tuple[str, ...]) -> float:
        # log-likelihood; the floor keeps an unplayed position from vetoing an
        # otherwise-best assignment outright
        return sum(math.log(max(shares[h][p], 1e-9)) for h, p in zip(team, order))

    best = max(permutations(POSITIONS), key=score)
    return dict(zip(team, best))


def _predicted_lane(
    my_hero_id: int, ally_picks: list[int], enemy_picks: list[int], data: ContextData
) -> PredictedLane:
    ally_pos = assign_positions(ally_picks, data.positions)
    enemy_pos = assign_positions(enemy_picks, data.positions)

    my_lane = LANE_BY_POSITION.get(ally_pos.get(my_hero_id, ""))
    if my_lane is None:
        return PredictedLane(None, [], [], None)

    with_ids = [h for h in ally_picks if h != my_hero_id and LANE_BY_POSITION[ally_pos[h]] == my_lane]
    vs_ids = [h for h in enemy_picks if LANE_BY_POSITION[enemy_pos[h]] == OPPOSING_LANE[my_lane]]

    return PredictedLane(
        lane=my_lane,
        with_heroes=[data.names.get(h, str(h)) for h in with_ids],
        vs_heroes=[data.names.get(h, str(h)) for h in vs_ids],
        matchup_delta=_lane_matchup_delta([my_hero_id, *with_ids], vs_ids, data),
    )


def _lane_matchup_delta(mine: list[int], theirs: list[int], data: ContextData) -> float | None:
    """Mean shrunk log5 advantage across every my-lane x their-lane pair.

    Computed straight from `stratz_hero_matchups` rather than read from
    `hero_matchup_advantage`, because that table only covers heroes in the
    Carry/Midlane/Offlane role lists — which come from `hero_role.csv`, which is
    scoped out of the coach. Supports would otherwise be missing entirely.

    Baselines come from the same table as the pair win rate, matching the fix in
    `01529a2`: log5 only isolates a real matchup residual when its baseline is
    computed on the same population.
    """
    deltas = []
    for a in mine:
        for b in theirs:
            pair = data.matchups.get((a, b))
            wr_a, wr_b = data.baselines.get(a), data.baselines.get(b)
            if pair is None or wr_a is None or wr_b is None:
                continue
            wins, games = pair
            if games == 0:
                continue
            denominator = wr_a * (1 - wr_b) + (1 - wr_a) * wr_b
            if denominator == 0:
                continue
            expected = wr_a * (1 - wr_b) / denominator
            raw = wins / games - expected
            deltas.append(raw * (games / (games + SHRINKAGE_K)))
    return sum(deltas) / len(deltas) if deltas else None


# --------------------------------------------------------------------------
# Comp tags
# --------------------------------------------------------------------------

def _comp(team: list[int], tags: dict[int, dict[str, bool]]) -> dict[str, int]:
    """How many heroes on this team carry each capability."""
    return {tag: sum(1 for h in team if tags.get(h, {}).get(tag)) for tag in TAGS}


# --------------------------------------------------------------------------

def build_context(
    my_hero_id: int,
    my_role: str | None,
    ally_picks: list[int],
    enemy_picks: list[int],
    data: ContextData,
) -> DraftContext:
    if len(ally_picks) != TEAM_SIZE or len(enemy_picks) != TEAM_SIZE:
        raise ValueError(f"ally_picks and enemy_picks must each contain {TEAM_SIZE} hero ids")
    if my_hero_id not in ally_picks:
        raise ValueError("my_hero_id must be one of ally_picks")

    curve = []
    for bucket in CHART_BUCKETS:
        mine = _team_win_rate(ally_picks, bucket, data.buckets)
        theirs = _team_win_rate(enemy_picks, bucket, data.buckets)
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
        predicted_lane=_predicted_lane(my_hero_id, ally_picks, enemy_picks, data),
        enemy_clocks=[c for h in enemy_picks for c in data.clocks.get(h, [])],
        my_comp=_comp(ally_picks, data.tags),
        their_comp=_comp(enemy_picks, data.tags),
    )


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

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

LOAD_POSITIONS = """
WITH recent AS (
    SELECT hero_id, position, games_played,
           DENSE_RANK() OVER (ORDER BY week DESC) AS wk
    FROM stratz_hero_positions
)
SELECT hero_id, position, SUM(games_played)
FROM recent
WHERE wk <= %s AND hero_id = ANY(%s)
GROUP BY hero_id, position
"""

LOAD_MATCHUPS = """
SELECT hero_id, vs_hero_id, wins, games_played
FROM stratz_hero_matchups
WHERE hero_id = ANY(%s) AND vs_hero_id = ANY(%s)
"""

LOAD_BASELINES = """
SELECT hero_id, SUM(wins)::numeric / SUM(games_played)
FROM stratz_hero_matchups
WHERE hero_id = ANY(%s)
GROUP BY hero_id
"""

LOAD_CLOCKS = """
WITH recent AS (
    SELECT hero_id, item_id, minute, games_played,
           DENSE_RANK() OVER (ORDER BY week DESC) AS wk
    FROM stratz_hero_item_purchase
    WHERE instance = 0
),
agg AS (
    SELECT hero_id, item_id, minute, SUM(games_played) AS n
    FROM recent WHERE wk <= %(weeks)s AND hero_id = ANY(%(heroes)s)
    GROUP BY hero_id, item_id, minute
),
totals AS (SELECT hero_id, item_id, SUM(n) AS total FROM agg GROUP BY hero_id, item_id),
cumulative AS (
    SELECT a.hero_id, a.item_id, a.minute, t.total,
           SUM(a.n) OVER (PARTITION BY a.hero_id, a.item_id ORDER BY a.minute) AS running
    FROM agg a JOIN totals t USING (hero_id, item_id)
),
median AS (
    SELECT hero_id, item_id, MIN(minute) AS median_minute, MAX(total) AS total
    FROM cumulative WHERE running >= total / 2.0
    GROUP BY hero_id, item_id
),
ranked AS (
    SELECT m.hero_id, m.item_id, m.median_minute, m.total,
           ROW_NUMBER() OVER (PARTITION BY m.hero_id ORDER BY m.total DESC) AS rn
    FROM median m JOIN stratz_items i ON i.id = m.item_id
    WHERE NOT i.is_component AND m.median_minute >= %(min_minute)s
)
SELECT hero_id, item_id, median_minute FROM ranked WHERE rn <= %(per_hero)s
ORDER BY hero_id, median_minute
"""

_TAG_COLUMNS = ", ".join('"' + t + '"' for t in TAGS)
LOAD_TAGS = f"SELECT hero_id, {_TAG_COLUMNS} FROM hero_tags WHERE hero_id = ANY(%s)"


def load_context_data(conn: psycopg.Connection, hero_ids: list[int], weeks: int = 2) -> ContextData:
    """Load every signal `build_context` needs for these ten heroes.

    All the "latest N weeks" rollups use DENSE_RANK, not ROW_NUMBER: these
    tables hold many rows per hero-week (14 duration buckets, 5 positions, one
    row per item-minute), so ROW_NUMBER would return a slice of a single week.
    See docs/progress.md.
    """
    buckets: BucketStats = {}
    for hero_id, bucket, wins, games in conn.execute(LOAD_BUCKET_STATS, (weeks, hero_ids)):
        buckets.setdefault(hero_id, {})[bucket] = (int(wins), int(games))

    positions: PositionStats = {}
    for hero_id, position, games in conn.execute(LOAD_POSITIONS, (weeks, hero_ids)):
        positions.setdefault(hero_id, {})[position] = int(games)

    matchups: MatchupStats = {
        (a, b): (int(wins), int(games))
        for a, b, wins, games in conn.execute(LOAD_MATCHUPS, (hero_ids, hero_ids))
    }
    baselines = {h: float(wr) for h, wr in conn.execute(LOAD_BASELINES, (hero_ids,))}

    names = dict(conn.execute("SELECT id, localized_name FROM heroes WHERE id = ANY(%s)", (hero_ids,)))
    item_names = dict(conn.execute("SELECT id, display_name FROM stratz_items"))

    clocks: dict[int, list[ItemClock]] = {}
    rows = conn.execute(
        LOAD_CLOCKS,
        {"weeks": weeks, "heroes": hero_ids, "min_minute": CLOCK_MIN_MINUTE, "per_hero": CLOCKS_PER_HERO},
    )
    for hero_id, item_id, median_minute in rows:
        clocks.setdefault(hero_id, []).append(
            ItemClock(
                hero_id=hero_id,
                hero_name=names.get(hero_id, str(hero_id)),
                item_name=item_names.get(item_id) or str(item_id),
                median_minute=int(median_minute),
            )
        )

    tags = {
        row[0]: dict(zip(TAGS, row[1:]))
        for row in conn.execute(LOAD_TAGS, (hero_ids,))
    }

    return ContextData(
        buckets=buckets, positions=positions, matchups=matchups, baselines=baselines,
        clocks=clocks, tags=tags, names=names,
    )
