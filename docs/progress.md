# Progress / handoff notes

Read this first when starting a new session. `proj_obj.txt` has the spec;
this file has what's actually built, key decisions, and gotchas that aren't
obvious from the code alone.

## Status

- Step 1 (ingestion), Step 2 (processing), Step 3 (engine), Step 4 (API),
  Step 5 (dashboard) — **done**. Not yet deployed anywhere — both currently
  only run locally (`uvicorn` + `streamlit run`).

## What's running

Database: Heroku Postgres (AWS RDS under the hood), credentials in
`src/app/config.py` (gitignored; copy `config.example.py` to get started).
Live connections require `sslmode="require"` — RDS rejects unencrypted
connections; every `psycopg.connect(...)` call in `ingestion/`, `engine/`,
and `api/db.py` sets this. Repo pushed to
https://github.com/haquynhnguyen1818/dota2 (main).

**API** (`src/app/api/`, FastAPI): `uvicorn app.api.main:app --port 8000`.
- `GET /heroes` — all hero id/name pairs.
- `GET /matchup-advantage/{role}/{vs_hero_id}` — Objective 1, full ranked
  list for a role vs. one opponent, wraps `hero_matchup_advantage`.
- `POST /draft-suggestions` — Objective 2, body `{"opponent_picks": [id,...]}`
  (1-5 ids, no dupes). Stateless: mirrors `draft_suggester.py`'s weighted-sum
  logic, but the caller resends the full accumulated pick list each call
  instead of the server holding session state.
- Interactive docs at `/docs`.

**Dashboard** (`src/app/dashboard/`, Streamlit): `streamlit run
src/app/dashboard/Home.py`. Calls the API over HTTP via `api_client.py`
(the `proj_folder_structure.md` open question — HTTP vs. direct
`engine`/`db` import — was decided in favor of HTTP, matching the original
lean). Two pages:
- `1_Matchup_Advantage.py` — role + opponent `st.selectbox` (both default
  blank via `index=None`), full ranked table.
- `2_Draft_Suggestions.py` — add up to 5 opponent picks one at a time via
  `st.session_state`, per-role top-10 best/worst tables update after each.
- Both use `st.table` (not `st.dataframe`) for result tables — `st.dataframe`
  only supports background/font *color* from a pandas Styler, not
  font-weight, since it renders via a canvas grid rather than HTML.
  `st.table` renders real HTML, so `components/styling.py`'s bold+color
  top-3-best (green) / top-3-worst (red) highlighting actually shows up.
- No custom mobile-responsive work needed — Streamlit ≥1.32 auto-stacks
  `st.columns()` on narrow viewports, and the app uses the default
  "centered" (not "wide") layout.

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

- **Deployment.** Nothing is hosted yet — cheapest options discussed
  (traffic expected to be a few users, very low):
  1. Streamlit Community Cloud (free) for the dashboard + skip hosting the
     API separately (dashboard imports `engine`/`db` directly instead of
     calling over HTTP) — $0 total, but reverses the HTTP-split decision
     above.
  2. Streamlit Community Cloud (free) + Render.com free web-service tier
     for the API — $0, but Render's free tier sleeps after ~15 min idle
     (~30-50s cold-start on the next request).
  3. Small always-on VPS (Hetzner CX22 ~$4-5/mo, DigitalOcean/Linode
     ~$5-6/mo) running both via the `docker-compose.yml` sketched in
     `proj_folder_structure.md` — keeps the HTTP split, no cold starts,
     small recurring cost + you own the box (updates, restarts).
  Not yet decided which to actually use.
- No automated tests exist yet for the engine or API logic (correctness
  has only been spot-checked manually/interactively so far, incl. live
  smoke tests of all 4 API endpoints against the real DB).
- `database_local.py` (a pre-reorg leftover with a real DB password and a
  live Stratz API JWT token) has been deleted and gitignored — if a copy
  surfaces again (e.g. from an old branch or backup), don't recommit it,
  and treat that Stratz token as compromised if it's ever found committed
  anywhere in history.
