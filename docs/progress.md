# Progress / handoff notes

Read this first when starting a new session. `proj_obj.txt` has the spec;
this file has what's actually built, key decisions, and gotchas that aren't
obvious from the code alone.

## Status

- Step 1 (ingestion), Step 2 (processing), Step 3 (engine) — **done**.
- Step 4 (API) and Step 5 (dashboard) — **not started**. See
  `proj_folder_structure.md` for the planned layout (FastAPI + Streamlit,
  src/app/api/, src/app/dashboard/).

## What's running

Database: Heroku Postgres, credentials in `src/app/config.py` (gitignored;
copy `config.example.py` to get started). Repo pushed to
https://github.com/haquynhnguyen1818/dota2 (main).

**Ingestion** (`src/app/ingestion/`):
- `load_heroes.py` — OpenDota `/heroes`, `/heroStats`, per-hero `/matchups` → `heroes`, `hero_stats`, `hero_matchups`.
- `load_stratz_heroes.py` — Stratz hero constants + winWeek/winDay/ban stats → `stratz_heroes`, `stratz_hero_stats`, `stratz_hero_win_week`, `stratz_hero_win_day`, `stratz_hero_bans`.
- `load_stratz_matchups.py` — Stratz `matchUp`, summed over the latest 2 weeks (see gotcha below) → `stratz_hero_matchups`.
- `load_heroes_roles.py` — loads `data/hero_role.csv` (hero → Carry/Midlane/Offlane/Supports, hand-curated by the user) → `roles_csv_import`, `hero_roles_csv_import`.

**Engine** (`src/app/engine/`):
- `compute_hero_matchup_advantage.py` — Objective 1. Builds `hero_matchup_advantage`: for each role list (Carry/Midlane/Offlane) and each possible opponent, ranks all heroes in that role by matchup advantage. Log5 (Bill James) expected-win-rate formula isolates matchup-specific edge from each hero's general form.
- `draft_suggester.py` — Objective 2. Interactive CLI: enter up to 5 enemy picks one at a time, get top-10-best/worst per role after each pick, weighted 0.8 for Support picks / 1.0 otherwise, excludes already-picked heroes.

Run either engine script directly (`python src/app/engine/...`) — the
package is pip-installed editable (`pip install -e .`) so `from app.config
import ...` resolves from any CWD.

## Key decisions & gotchas (don't rediscover these the hard way)

- **`hero_wr`/`vs_hero_wr` = latest 2 weeks only**, not lifetime, not a
  single week. Summed `wins`/`games_played` from `stratz_hero_win_week`'s
  two most recent `week` buckets. Chosen over lifetime because the user
  wants current-meta win rates, not a season average.
- **`wr_a_b` must be on the same time basis as `hero_wr`.** Stratz's
  `matchUp` query with no `week` arg silently returns only the *single*
  latest week (not lifetime, as originally assumed) — confirmed by GraphQL
  introspection and comparing raw counts. `load_stratz_matchups.py` now
  explicitly fetches `week=<2 latest buckets>` and sums them, so `wr_a_b`
  and `hero_wr` cover the same window. If `hero_wr`'s window changes again
  (e.g. "latest 3 weeks"), `load_stratz_matchups.py` must change to match,
  or the advantage numbers will look subtly wrong again.
- **`xWr_a_b`** is the log5 formula: `hero_wr*(1-vs_hero_wr) /
  (hero_wr*(1-vs_hero_wr) + (1-hero_wr)*vs_hero_wr)` — isolates matchup edge
  from general hero strength.
- **Ranking partition is `(role_name, vs_hero_id)`**, i.e. for a *fixed
  opponent*, rank all heroes in a role list best-to-worst
  (`rank_vs_hero`, 1..36/38/44). This was the correct reading of the spec
  after a couple of false starts (partition by hero_id was tried and
  reverted) — verified against the user's own sample data before landing
  here. Don't flip this without re-confirming against a sample.
- **Supports never overlap with Carry/Midlane/Offlane** in
  `hero_roles_csv_import` — verified empirically, which is why
  `draft_suggester.py` can use a simple binary Support/non-Support check
  for the 0.8/1.0 weight.
- When the user says a ranking or number "looks off," pull the exact row
  they're questioning and cross-check every intermediate value (games_played,
  wins, hero_wr, etc.) against the live DB before assuming a logic bug —
  more than once the real cause was Stratz's rolling data window having
  moved between when the user pulled a reference sample and when the query
  re-ran, not a formula error.
- `hero_role.csv`'s `hero_id` column maps directly to `heroes.id` /
  `stratz_heroes.id` (Valve's hero IDs) — confirmed 1:1, only 3 harmless
  name-casing mismatches (e.g. "BeastMaster" vs "Beastmaster").

## Next up

- Step 4: FastAPI service exposing `hero_matchup_advantage` /
  draft-suggestion logic.
- Step 5: Streamlit dashboard. Open decision from `proj_folder_structure.md`:
  dashboard calls the API over HTTP (recommended) vs. importing
  `engine`/`db` directly — not yet decided in practice.
- No automated tests exist yet for the engine logic (formula correctness
  has only been spot-checked manually/interactively so far).
