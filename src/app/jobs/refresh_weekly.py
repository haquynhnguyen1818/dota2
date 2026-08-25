"""Weekly refresh of every time-varying table. Run from cron on the Droplet.

    docker compose -f infra/docker-compose.yml run --rm api \
        python -m app.jobs.refresh_weekly

**Stratz publishes completed weeks only.** A week starts Thursday 00:00 UTC, so
the newest data available is always the week that closed on the most recent
Thursday -- on 2026-08-25 that was the week of 2026-08-13. No amount of
re-running gets anything fresher; the job exists to pick up each new week as it
closes, which nothing did before.

Every step is an idempotent upsert, so re-running is safe and a partial run is
repaired by the next one. That is why a failing step gets one retry and then
lets the rest proceed: transient Stratz flakiness on one loader should not cost
the other nine. Failures are collected and the process exits non-zero, so cron
surfaces them.

⚠️ **The Stratz token is bound to a single IP address** -- calling the API from
a second machine returns `403 You cannot use different IP Addresses when using
the API`. Since this job owns the schedule, the Droplet owns the token. Running
a Stratz loader from a laptop re-binds it and breaks the next cron run.

Ordering matters in one place -- `compute_hero_matchup_advantage` rebuilds a
derived table and must run after the matchup and win-week loaders that feed it.

The two hand-authored CSV loaders (`load_heroes_roles`, `load_hero_tags`) are
deliberately absent: they only change when the file changes, which is a manual
act, and re-reading them weekly would just be noise in the log.
"""
import sys
import time
import traceback
from datetime import UTC, datetime

import psycopg

from app.credentials import db_kwargs
from app.engine import compute_hero_matchup_advantage
from app.ingestion import (
    load_heroes,
    load_patch_notes,
    load_players,
    load_stratz_hero_duration,
    load_stratz_hero_positions,
    load_stratz_heroes,
    load_stratz_item_timings,
    load_stratz_matchups,
    load_stratz_synergy,
)

STEPS = [
    ("heroes, hero_stats, hero_matchups (OpenDota)", load_heroes.main),
    ("stratz heroes, win week, win day, bans", load_stratz_heroes.main),
    ("stratz matchups", load_stratz_matchups.main),
    ("stratz synergy", load_stratz_synergy.main),
    ("stratz duration win rates", load_stratz_hero_duration.main),
    ("stratz hero positions", load_stratz_hero_positions.main),
    ("stratz item timings", load_stratz_item_timings.main),
    ("patch notes", load_patch_notes.main),
    ("player history", load_players.main),
    ("hero matchup advantage (derived)", compute_hero_matchup_advantage.main),
]

# Every table the coach and the suggester read on a rolling 2-week window. If
# these disagree, the two features are answering from different time bases --
# the documented cause of "the numbers look off". See docs/progress.md.
RETRY_DELAY_SECONDS = 30

WEEK_TABLES = [
    "stratz_hero_win_week",
    "stratz_hero_duration_wr",
    "stratz_hero_positions",
    "stratz_hero_item_purchase",
]


def report_latest_weeks() -> None:
    """Print the newest week in each rolling table, so the log answers the only
    question that matters: did this run actually pick up a new week?"""
    with psycopg.connect(**db_kwargs()) as conn:
        weeks = {
            table: conn.execute(f"SELECT max(week) FROM {table}").fetchone()[0]
            for table in WEEK_TABLES
        }
        # By release date, not max(version) -- version is text, and "7.9"
        # sorts above "7.10".
        row = conn.execute(
            "SELECT version FROM patch_notes ORDER BY released_at DESC LIMIT 1"
        ).fetchone()
        version = row[0] if row else "none"

    for table, week in weeks.items():
        stamp = datetime.fromtimestamp(week, UTC).strftime("%Y-%m-%d") if week else "none"
        print(f"  {table:<28} {stamp}", flush=True)
    print(f"  {'patch_notes':<28} {version}", flush=True)

    distinct = {week for week in weeks.values() if week is not None}
    if len(distinct) > 1:
        print(
            "  WARNING: rolling tables are on different weeks -- the coach and the "
            "suggester will disagree. Re-run the job.",
            flush=True,
        )


def run_step(step) -> bool:
    """Run one loader, with a single retry.

    Stratz truncates large responses intermittently (ChunkedEncodingError on a
    chunked gzip stream), and a step that fails where its neighbours succeed is
    exactly what leaves the rolling tables on different weeks. One retry is
    enough for the flakiness actually observed; a step that fails twice has a
    real problem and should be read in the log.
    """
    for attempt in (1, 2):
        started = time.monotonic()
        try:
            step()
        except Exception:
            traceback.print_exc()
            print(f"attempt {attempt} FAILED after {time.monotonic() - started:.1f}s", flush=True)
            if attempt == 1:
                print(f"retrying in {RETRY_DELAY_SECONDS}s", flush=True)
                time.sleep(RETRY_DELAY_SECONDS)
        else:
            print(f"ok in {time.monotonic() - started:.1f}s", flush=True)
            return True
    return False


def run() -> int:
    print(f"=== weekly refresh started {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC ===", flush=True)
    started = time.monotonic()
    failures = []

    for name, step in STEPS:
        print(f"\n--- {name} ---", flush=True)
        if not run_step(step):
            failures.append(name)

    print("\n--- latest week per rolling table ---", flush=True)
    try:
        report_latest_weeks()
    except Exception:
        traceback.print_exc()

    elapsed = time.monotonic() - started
    if failures:
        print(f"\n=== FAILED in {elapsed:.1f}s: {', '.join(failures)} ===", flush=True)
        return 1
    print(f"\n=== all {len(STEPS)} steps ok in {elapsed:.1f}s ===", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
