# Progress / handoff notes

Read this first when starting a new session. `proj_obj.txt` has the spec;
this file has what's actually built, key decisions, and gotchas that aren't
obvious from the code alone.

## Status

- **Phase 1 (steps 1-5) and Phase 2 (steps 1-4) are both done** — see
  `proj_obj.txt` for the per-step spec and completion notes. Step 5
  (frontend) has two implementations: the original Streamlit dashboard
  (`src/app/dashboard/`, still present, no longer the primary UI) and a
  static HTML/CSS/vanilla-JS frontend (`web/`) that replaced it as of
  2026-08-21 — see "Why the frontend changed" below.
  **Fully deployed and live**: `web/` on Cloudflare
  (`https://dota2.haquynh-nguyen.workers.dev`), API + Postgres on a
  DigitalOcean Droplet behind Caddy (`https://165-22-246-179.sslip.io`).
  Phase 2's synergy/player-history/shrinkage work (see below) was deployed
  the same way on 2026-08-21: pushed to `origin/main`, Droplet's `api`
  container rebuilt via `docker compose up -d --build api`, Cloudflare
  auto-deployed `web/` on push — both verified live against the real
  production URLs afterward. Heroku Postgres has been migrated from and
  retired (add-on deleted) — see `docs/deploy_todo.md` for the full
  step-by-step history.

### Why the frontend changed

User decided against Streamlit Community Cloud for hosting and wants the
deployed app always-live with zero cold-start (rules out free-tier PaaS
options that sleep on idle, e.g. Render's free web-service tier). Since
Streamlit itself only runs for free on Community Cloud — anywhere else it
needs its own always-on paid host same as the API would — the zero-cold-start
requirement made a lighter-weight static frontend worth it: it can be hosted
for free with no cold start on Cloudflare Pages/Netlify/GitHub Pages, while
only the FastAPI backend needs an always-on paid host (VPS or similar) either
way. The user also had a hand-built dark-themed mockup (`data/draft-terminal.html`,
untouched, kept as the design reference) they wanted the real app to look
like — replicating that inside Streamlit's widget model wasn't practical
(per-row bar charts, pill tabs, chip animations), so building a real static
frontend solved both problems at once. CORS (`allow_origins=["*"]`, no
credentials involved) was added to `src/app/api/main.py` so the browser can
call the API cross-origin.

## What's running

Database: Postgres running in a container on the DigitalOcean Droplet
(`infra/docker-compose.yml`) — Heroku Postgres (the original host) has been
retired. Production (`api`'s own container) reaches it over the internal
Docker network with `DB_SSLMODE=disable` (self-hosted Postgres, no SSL
configured — that's fine, it's not internet-exposed).

**Local dev**: `src/app/config.py` (gitignored; copy `config.example.py` to
get started) now points `creds_opendota` at `127.0.0.1:5432` with
`'sslmode': 'disable'`, reached via an SSH tunnel to the Droplet rather than
a separate local Postgres install — reuses the real (small, low-traffic)
production data with no separate sync step. The Droplet's Postgres is bound
to its own loopback only (`127.0.0.1:5432:5432` in docker-compose, not
exposed publicly), so before running anything locally — the API, or any
`ingestion`/`engine` script — start the tunnel first:
`ssh -i ~/.ssh/do_dota2_deploy -N -L 5432:127.0.0.1:5432 root@165.22.246.179`.
All `psycopg.connect(...)` calls across `ingestion/`, `engine/`, and
`api/db.py` read `sslmode` from `creds_opendota` (default `"require"` if
unset) rather than hardcoding it, specifically so this local/tunneled setup
and any future SSL-requiring host both work without code changes. Repo
pushed to https://github.com/haquynhnguyen1818/dota2 (main).

**API** (`src/app/api/`, FastAPI): `uvicorn app.api.main:app --port 8000`.
- `GET /heroes` — all hero id/name pairs.
- `GET /matchup-advantage/{role}/{vs_hero_id}` — Objective 1, full ranked
  list for a role vs. one opponent, wraps `hero_matchup_advantage`.
- `POST /draft-suggestions` — Objective 2, body `{"opponent_picks": [id,...],
  "ally_picks": [id,...]}` (`opponent_picks` 1-5 ids required, no dupes;
  `ally_picks` 0-5 ids optional, no dupes, must not overlap
  `opponent_picks`). Stateless: mirrors `draft_suggester.py`'s weighted-sum
  logic, but the caller resends the full accumulated pick lists each call
  instead of the server holding session state. Each candidate's
  `total_advantage` now sums shrunk matchup advantage (vs `opponent_picks`)
  and shrunk synergy (with `ally_picks`) — see the Phase 2 step 2 entry
  below. `DraftSuggestion.synergy_breakdown` is additive to the response
  shape (empty list when `ally_picks` is omitted). Optional
  `player_account_id` (Phase 2 step 4): if given, must be a known id in
  `players` (404 otherwise) and each suggestion gets a `player_history`
  field (`games_played`/`wins`/`win_rate`, `null` if that player has no
  games on that hero — e.g. a private profile with no data pulled).
  Annotation only, does not affect ranking — see the step 4 entry below.
- `POST /draft-analysis` — Post-draft coach, Phase B3 (see `coaching_plan.md`).
  Body `{"my_hero_id": id, "my_role": null, "ally_picks": [5 ids],
  "enemy_picks": [5 ids]}`. **Requires exactly 5 and 5** — this fires once a
  draft is complete, unlike `/draft-suggestions` which answers mid-draft from
  partial picks. `my_hero_id` must be in `ally_picks`; teams may not overlap or
  contain dupes. **`my_role` is optional** (`Carry|Midlane|Offlane|Supports`,
  validated only when supplied) and never inferred — the web UI stopped sending
  it once the role selector was removed, since the curve doesn't read it. Phase
  G re-collects it. Returns the power curve per duration bucket (`my_win_rate`,
  `their_win_rate`, `delta`), the `crossover_bucket`, and a `tempo_verdict`
  of `you_are_faster`/`you_win_long`/`even`/`unknown`.

  **`my_hero_id` does not affect the curve** — the curve is your five heroes
  against their five, so changing which ally is "you" legitimately returns an
  identical curve. Verified live: the selector refetches and the SVG points
  come back byte-identical. It is carried for Phase G, where it matters.
- `GET /players` — public players only (id/name pairs), backs the web
  frontend's player-history selector. Added alongside the web UI build-out
  below; private players exist in the `players` table but are filtered out
  here since they have no `player_hero_stats` rows to show.
- Interactive docs at `/docs`.

**Web** (`web/`, static HTML/CSS/vanilla JS — the current primary UI):
serve with any static file server, e.g. `python -m http.server 5500` from
inside `web/`, then open `index.html`/`matchup.html`. Talks to the API via
`fetch()` in `js/api.js`; `js/config.js` holds `API_BASE_URL` — update it
before deploying. Two pages, dark "Draft Terminal" theme matching
`data/draft-terminal.html`:
- `index.html` (`js/draft.js`) — Objective 2. Opponent picks as removable
  chips (native flexbox `flex-wrap`, no framework needed — sizes to content
  and wraps on overflow for free, unlike the Streamlit version which needed
  a CSS workaround for the same thing), added via the same searchable
  combobox as the matchup page (see `js/combo.js` below) rather than a plain
  `<select>`. Carry/Midlane/Offlane tabs. **Top best returns 20 from the API
  (`TOP_N_BEST` in `api/routers/draft.py`) but the page only renders the
  first 10 by default, with a "Show all 20 heroes" button to expand — top
  worst stays at 10 (`TOP_N_WORST`), no pagination there.** Both lists show a
  WR column (green ≥50%) and a bar visualizing advantage magnitude. Rows are
  clickable — expands inline sub-rows (same list, not a separate table)
  showing each opponent's individual advantage, sorted descending
  server-side (`_build_suggestion`). Mobile gets a segmented best/worst
  toggle instead of the two-column grid. **Ally picks** (Phase 2 step 2):
  a second chip section mirroring opponent picks exactly (`state.allyPicks`,
  its own combo/add/reset), sent as `ally_picks`. The two hero combos
  mutually exclude each other's picks (can't pick the same hero as both an
  opponent and an ally) — `options` callbacks filter against both
  `state.opponentPicks` and `state.allyPicks`. Expanding a row now also
  shows synergy sub-rows (`↳ with <hero>`) after the existing matchup
  sub-rows (`↳ vs <hero>`), from `synergy_breakdown`. **Player history**
  (Phase 2 step 4): a single-select combo (same `setupCombo()` pattern as
  the matchup page's role/hero selectors, not the chip pattern) sourced from
  the new `GET /players` endpoint, sent as `player_account_id`. When a
  player is selected, each row's WR line grows a `· You: Ng, W% WR` suffix
  from `player_history`; clearing the player removes it. Purely additive to
  the row — matches the "annotate only" decision from step 4, doesn't touch
  ranking or bar width.
- `js/coach.js` — **Post-draft coach panel** (Phase C, see `coaching_plan.md`).
  A card on `index.html` between the player-history selector and the role tabs.
  Locked until **both** chip lists hold 5, showing a countdown of what's still
  missing; at 5v5 it reveals a "which one is me" combo (options are the ally
  picks only) and draws the power curve. "Me" defaults to the first ally so
  the curve is on screen without a click — safe because `my_hero_id` doesn't
  affect the curve in v1, it's only carried through for the later LLM phase.
  **There is no role selector**: it was removed after Phase C shipped because
  the curve doesn't read role, so the control did nothing visible. Phase G
  adds it back. Chart is hand-rolled inline SVG, no library.
  **The y-axis fits the data with a 2pp floor** (`MIN_SPAN`): averaging five
  heroes pulls hard toward 50%, so real deltas are often under 2pp and a
  0-100% axis would draw every draft as two flat lines. 50% is always kept in
  frame as the reference. Has its own stale-response guard (`coachSeq`), same
  reason as `draft.js`'s. `draft.js` touches this in exactly two places:
  `refreshCoach()` at the top of `refreshSuggestions()` (every pick mutation
  routes through there) and `setupCoach()` in `init()`.
- `js/combo.js` — the searchable-combobox widget (`setupCombo()`) shared by
  both pages; `options` can be a static array or a callback (draft.js uses a
  callback so the hero-picker's option list stays live-filtered against
  `opponentPicks` without re-initializing the combo on every add/remove).
- `matchup.html` (`js/matchup.js`) — Objective 1, matches
  `data/matchup-advantage.html`'s mockup (also untouched, kept as reference):
  searchable combobox selectors (custom, not native `<select>` — supports
  typeahead filtering and a clear/× button) for role and opponent hero, a
  context strip showing the opponent's own baseline WR, and a paginated
  ranked list (`Show all N heroes` / `Show top 10 only`). Role options are
  hardcoded to the 3 the backend actually supports (`Carry`/`Midlane`/`Offlane`
  in `web/js/config.js`'s `ROLES`) — the mockup's own demo data additionally
  listed Soft/Hard Support, which `hero_matchup_advantage` has no ranking
  data for (supports are only used as opponent-side weighting in the draft
  suggester, not ranked in a role list themselves), so those were dropped
  rather than shown disabled. Top-3/bottom-3 rows are highlighted green/red
  only when the row's own advantage sign agrees with its tier position
  (matches the mockup's `idx<3 && adv>0` / `idx>=total-3 && adv<0` logic
  exactly — an edge case, like a top-3 "best" pick that's still net-negative,
  intentionally stays unhighlighted rather than being forced green).
- **Stale-response guard**: `draft.js` tracks `requestSeq` +
  `state.suggestionsForPicks`. Adding/removing picks in quick succession
  fires overlapping `POST /draft-suggestions` calls (each takes ~3s — see
  gotcha below); without this guard a slower *earlier* request can resolve
  after a faster *later* one and silently overwrite it with stale data. Any
  future async refetch added to this page needs the same guard.
- No automated JS test framework wired up; verified via a throwaway
  Playwright script driving a real headless Chromium against the live API
  (chips, tab switching, click-to-expand + sort order, WR coloring, CORS,
  tier highlighting all confirmed working end-to-end). Same approach used
  to verify the ally-picks/player-history UI: opponent+ally chip add/remove,
  mutual exclusion between the two hero combos, player select/clear, full
  reset, and the expanded row's `↳ vs`/`↳ with` sub-row values — all
  cross-checked against the exact numbers already verified against the API
  directly (Bloodseeker vs Anti-Mage + Pudge ally = 5.58% matchup + -0.44%
  synergy = 5.14% total, AAA's 21g/61.9% WR on Bloodseeker).

**Dashboard** (`src/app/dashboard/`, Streamlit) — superseded by `web/` above,
kept in the repo but not the primary UI anymore. `streamlit run
src/app/dashboard/Home.py`. Calls the API over HTTP via `api_client.py`. Two
pages (`1_Matchup_Advantage.py`, `2_Draft_Suggestions.py`); the draft page
uses `st.dataframe(..., on_select="rerun")` (not `st.table`) so rows are
clickable — same click-to-expand-breakdown and chip-removal behavior as the
web version, implemented Streamlit-side instead. Not being extended further
now that `web/` is the primary UI; fine to delete once the static frontend
is confirmed working in production.

**Ingestion** (`src/app/ingestion/`):
- `load_heroes.py` — OpenDota `/heroes`, `/heroStats`, per-hero `/matchups` → `heroes`, `hero_stats`, `hero_matchups`.
- `load_stratz_heroes.py` — Stratz hero constants + winWeek/winDay/ban stats → `stratz_heroes`, `stratz_hero_stats`, `stratz_hero_win_week`, `stratz_hero_win_day`, `stratz_hero_bans`.
- `load_stratz_matchups.py` — Stratz `matchUp`, summed over the latest 2 weeks (see gotcha below) → `stratz_hero_matchups`.
- `load_heroes_roles.py` — loads `data/hero_role.csv` (hero → Carry/Midlane/Offlane/Supports, hand-curated by the user) → `roles_csv_import`, `hero_roles_csv_import`.
- `load_stratz_synergy.py` — Phase 2 step 1. Stratz `matchUp`'s `with` field (duo win rates, heroes on the same team), summed over the latest 2 weeks like `load_stratz_matchups.py` → `stratz_hero_synergy` (`hero_id`, `with_hero_id`, `games_played`, `wins`, `synergy`; directed pair, PK on both columns). 16,002 rows = full 127×126 directed matrix. `synergy` is Stratz's own precomputed TrueSynergy offset (per user request), games-played-weighted across the 2 weeks since it's a per-week ratio, not a raw count — can't just be summed like `games_played`/`wins`.
- `load_stratz_hero_duration.py` — Post-draft coach, Phase A1 (see `coaching_plan.md`). Stratz `winWeek` with `groupBy: HERO_ID_DURATION_MINUTES` → `stratz_hero_duration_wr` (`hero_id`, `week`, `duration_bucket`, `games_played`, `wins`; PK on the first three). 33,782 rows = 127 heroes × 19 weeks × 14 buckets, a perfectly dense grid. One API call — `take` counts *weeks*, not rows. **`duration_bucket` is Stratz's `durationMinute`, a bucket index (0-14), not a minute value** — renamed on the way in so it can't be misread; buckets are ~5 min wide. All weeks are stored raw; consumers roll up to the latest 2 at query time. **Deliberately a separate table from `stratz_hero_win_week`** rather than filling in that table's unused all-zeros `duration_minute` column — see the gotcha below.
- `load_stratz_hero_positions.py` — Post-draft coach, Phase E1. Stratz
  `heroStats.stats(groupByPosition: true)` → `stratz_hero_positions`
  (`hero_id`, `week`, `position`, `games_played`, `wins`; PK on the first
  three). 1,270 rows = 127 heroes × 2 weeks × 5 positions, dense. 1 call per
  week. **This is the coach's only position source** — `hero_role.csv` stays
  scoped to the pick-suggester (user decision). Sanity-checked: Anti-Mage 92%
  POSITION_1, Crystal Maiden 71% POSITION_5, Invoker 70% POSITION_2, with
  Pudge and Earthshaker correctly reading as flexible (~34% top position).
  ⚠️ **`stats` is a parsed-match subset** (~31% of `winWeek`'s volume — positions
  can only be inferred from a parsed match), so its absolute counts are not
  comparable with `stratz_hero_win_week`/`stratz_hero_duration_wr`. Fine for a
  *distribution* question. Also note `stats` echoes `week` as a week **index**
  (2954) while every other table uses Stratz's Unix timestamp (1786579200 =
  604800 × 2954, the same week) — the loader stores the requested timestamp so
  this table joins cleanly with the rest.
- `load_stratz_item_timings.py` — Post-draft coach, Phase E2. Stratz
  `constants.items` → `stratz_items` (id/short_name/display_name), and
  `heroStats.itemFullPurchase` → `stratz_hero_item_purchase` (`hero_id`,
  `week`, `item_id`, `minute`, `games_played`, `wins`; PK on the first four).
  Stores the **raw per-minute distribution**, not a precomputed median, so
  p25/p75 or win-rate-weighted timings stay available without a re-fetch.
  `heroId` is singular on this endpoint → 1 call per hero per week, 254 total,
  throttled at 0.3s to stay inside Stratz's 250/min. ⚠️ The item list includes
  **build-up components**, not just finished items (Anti-Mage's includes
  Perseverance and Yasha next to Battle Fury and Manta Style) — choosing which
  item counts as a "threat" is a scoring question left to Phase E4.
- `load_players.py` — Phase 2 step 3. Parses the hand-curated `docs/players_id.txt` (`Name: account_id. Profile status: public|private.`) → `players` (all players, public and private). For players marked public only, fetches OpenDota `/players/{account_id}/heroes` → `player_hero_stats` (per-hero `games_played`/`wins`/`with_*`/`against_*`/`last_played`, zero-game rows skipped). Private profiles are recorded in `players` (so they're known) but no history is fetched for them — OpenDota returns all-zero data for private profiles anyway, and it'd just be wasted API calls. Stratz is *not* used for player history — see gotcha below.

**Engine** (`src/app/engine/`):
- `compute_hero_matchup_advantage.py` — Objective 1. Builds `hero_matchup_advantage`: for each role list (Carry/Midlane/Offlane) and each possible opponent, ranks all heroes in that role by matchup advantage. Log5 (Bill James) expected-win-rate formula isolates matchup-specific edge from each hero's general form.
- `draft_suggester.py` — Objective 2. Interactive CLI: prompts up to 5 of
  your own team's picks up front (`ally_picks`, Phase 2 step 2), then up to
  5 enemy picks one at a time, get top-10-best/worst per role after each
  opponent pick, weighted 0.8 for Support opponent picks / 1.0 otherwise,
  excludes heroes either team has already picked. Each candidate's score is
  shrunk matchup advantage (vs opponents) + shrunk synergy (with allies) —
  see the shrinkage entry below. Also prompts once for an optional OpenDota
  account id (Phase 2 step 4) and, if given, prints that player's own
  games/win-rate on each suggested hero from `player_hero_stats` inline —
  annotation only, doesn't change ranking or which heroes are suggested.

Run either engine script directly (`python src/app/engine/...`) — the
package is pip-installed editable (`pip install -e .`) so `from app.config
import ...` resolves from any CWD.

## Key decisions & gotchas (don't rediscover these the hard way)

- **`hero_wr`/`vs_hero_wr` come from `stratz_hero_matchups`, not
  `stratz_hero_win_week`** — changed in `01529a2`. Each hero's baseline is its
  games-played-weighted win rate across all of its matchup rows, i.e. the
  *same population* as `wr_a_b`. That is the whole point: log5 only isolates a
  real matchup-specific residual when its baseline is computed on the same
  population as the number it's subtracted from. Stratz's `matchUp` samples a
  "significant interaction" subset rather than a uniform slice of every match
  (per-hero totals measured at 0.89-2.11x `winWeek`'s), so using `winWeek`'s
  blanket win rate as the baseline handed flex/summon heroes a systematic edge
  against nearly every opponent — Meepo, Visage and Arc Warden run +4.40,
  +4.34 and +3.75 percentage points higher in the matchUp population than in
  winWeek's. A useful side effect: because both sides of the subtraction now
  come from one table, they are automatically on the same time basis, so the
  old "keep the two windows in sync" hazard is gone.
- **`wr_a_b` must be on the same time basis as `hero_wr`.** Stratz's
  `matchUp` query with no `week` arg silently returns only the *single*
  latest week (not lifetime, as originally assumed) — confirmed by GraphQL
  introspection and comparing raw counts. `load_stratz_matchups.py` now
  explicitly fetches `week=<2 latest buckets>` and sums them. That still
  governs what lands in `stratz_hero_matchups` and so still defines the
  advantage window. (The clause that used to live here — "keep this in sync
  with `hero_wr`'s window or the numbers go subtly wrong" — no longer applies
  since `01529a2`: `hero_wr` is now derived from this same table, so the two
  cannot drift apart.)
- **Two different populations are now displayed on the same page — this is
  expected, not a bug.** `hero_wr` in `/draft-suggestions` rows comes from the
  `matchUp` population; the coach's power curve comes from the `winWeek`
  population, because `winWeek` is the only place duration data exists. For
  most heroes they agree closely (median gap 0.65pp, p90 1.73pp) but for
  flex/summon heroes they diverge by up to 4.4pp, so the same hero can show
  slightly different win rates in the two panels. **Don't "fix" this by moving
  the curve onto matchUp data** — there is no matchUp-by-duration breakdown,
  and `winWeek` is the correct population for a duration question anyway,
  being a uniform slice of all games. Verified centred: pooled across all
  heroes, every duration bucket 3-13 sits at exactly 50.00%, so curve deltas
  are pure relative signal with no per-bucket baseline drift.
- **Duration buckets are 5 minutes wide: bucket `b` = minutes `[5b, 5b+5)`,
  bucket 14 = 70+.** Established structurally, not by direct measurement.
  Stratz's per-minute data caps at 75 min (`stats` with `minTime:60,
  maxTime:100` returns rows 60..75 only), and `winWeek` exposes bucket indices
  0..14 — width 5 is the *only* width where the top bucket lands on that cap
  (14×5 = 70-75; width 4 caps at 60, width 6 needs 90). Corroborated by the
  median landing in bucket 7 → 35-40 min, which matches real Dota.
  **Why there is no direct confirmation:** `heroStats.stats` is the only
  endpoint exposing a per-minute survival curve, but it covers just ~31% of
  the matches `winWeek` does for the same hero and week (231,702 vs 745,573)
  — it is a *parsed-match* subset, which skews longer (its median is 42 min
  vs bucket 7's 35-40). Inverting its CDF against bucket fractions yields
  incoherent widths drifting 3.1→6.1 min, so it cannot serve as proof. Don't
  redo that cross-check expecting it to work.
- **Trust duration buckets 3-13 only (15-70 min, 98.3% of games).** Bucket 0
  is anomalous — 1.05% of games, *larger* than bucket 2 (0.46%), while bucket
  1 has exactly zero rows across all 33,782 rows. That pattern reads like a
  catch-all/unknown bucket rather than a literal 0-5 min bin, so don't label
  it as minutes or lean on it. Bucket 14 (70+) is a 0.12% tail.
- **Rolling up "latest 2 weeks" — `ROW_NUMBER` vs `DENSE_RANK` depends on the
  table's shape.** `stratz_hero_duration_wr` has **14** rows per hero-week
  (one per duration bucket), so `ROW_NUMBER() OVER (PARTITION BY hero_id ORDER
  BY week DESC) <= 2` there keeps 2 rows spanning a *single* week and 2
  duration buckets, not 2 weeks — confirmed empirically, not theoretical. Any
  rollup on that table must use `DENSE_RANK() OVER (ORDER BY week DESC) <= 2`
  or an explicit `week IN (...)`; `engine/draft_context.py`'s
  `load_bucket_stats` is the reference. The rule generalises: `ROW_NUMBER` is
  only safe on a table with exactly one row per hero-week.
  *Historical:* `compute_hero_matchup_advantage.py` used to carry this exact
  `ROW_NUMBER` pattern against `stratz_hero_win_week`, which is why duration
  data was given its own table rather than filling in that table's unused
  `duration_minute` column. Commit 01529a2 rebased `hero_wr` onto
  `stratz_hero_matchups`, so that consumer no longer reads the week table and
  that specific hazard is gone. The separate table stands on its own merits
  now — writing bucket rows into `stratz_hero_win_week` would collide bucket 0
  with the per-week total row on the same PK.
- **Hero rosters: read ids from the DB, never a hardcoded range.** A planning
  probe using `range(1, 150)` silently missed Largo (id 155) and undercounted
  by one hero's entire grid. `stratz_heroes` has 127 rows with ids up to 155.
- **`take` on Stratz's `winWeek` counts weeks, not rows.** `take: 2000` returns
  every retained week for every hero id passed, not 2000 rows.
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
- **`stratz_hero_synergy` is directional and the two directions don't
  perfectly agree.** Querying `matchUp(heroIds:[1,50]).with` from hero 1's
  row gives a slightly different `matchCount`/`winCount` for the (1, 50)
  pair than hero 50's row gives for (50, 1) (e.g. 5841/3059 vs 5757/3019 in
  one snapshot — Stratz-side sampling, not a bug on our end). Stored as-is,
  same convention as `stratz_hero_matchups` (directed `hero_id`/other-hero
  columns, no forced symmetry). Also note: Stratz's `with` data exposes a
  pre-computed `synergy` field (their own TrueSynergy offset) alongside the
  raw `matchCount`/`winCount` — per user request this **is** pulled and
  stored (unlike the sibling `winRateHeroId1`/`winRateHeroId2`/`winsAverage`
  fields, which weren't asked for and were skipped). Since `synergy` is a
  per-week ratio, not a raw count, it can't be summed across the 2-week
  window the way `games_played`/`wins` can — `load_stratz_synergy.py`
  combines the 2 weeks as a `games_played`-weighted average instead. Phase 2
  step 2 can still independently recompute an expected-WR offset the same
  log5 way `compute_hero_matchup_advantage.py` does for Objective 1, using
  the raw `games_played`/`wins` columns, if that ends up preferred over
  trusting Stratz's own metric.
- **Phase 2 step 2 — synergy folded into `draft-suggestions`, shrunk by
  sample size.** Design (chosen after presenting alternatives to the user):
  extend `opponent_picks`-only scoring to also take `ally_picks`, and sum
  shrunk matchup advantage (vs opponents) + shrunk synergy (with allies)
  into one score per candidate, same as `hero_matchup_advantage.advantage`
  is already the sole signal today. `SHRINKAGE_K = 500` (duplicated as a
  module constant in both `draft_suggester.py` and `api/routers/draft.py`,
  not centralized — small enough constant that a shared config felt like
  premature abstraction) implements the empirical-Bayes note added to
  `proj_obj.txt` Phase 2 step 2: `delta_adjusted = delta_raw * n/(n+K)`,
  applied to **both** `advantage` (n = `stratz_hero_matchups.games_played`,
  joined in) and `synergy` (n = `stratz_hero_synergy.games_played`, already
  stored) — small-sample pairs get pulled toward 0 instead of dominating the
  ranking. `synergy` is also `/100`'d before shrinking/summing to match
  `advantage`'s fraction scale (see the unit-mismatch note above). Shrinkage
  is scoped to the draft-suggestion formula only — `hero_matchup_advantage`
  itself and the standalone `GET /matchup-advantage/{role}/{vs_hero_id}`
  (Objective 1) are untouched, since the shrinkage note was raised
  specifically in the context of combining signals for pick suggestions.
  Ally weighting is uniform (1.0, no Support/non-Support split) — that
  discount only made sense for opponent picks (matters less to counter a
  support) and wasn't asked for on the ally side.
- **Deferred: lane-specific synergy split (`proj_obj.txt` Phase 2 step 2,
  note b).** Stratz does expose a laning-phase-specific query —
  `heroStats.laneOutcome(heroId, isWith: true, positionIds: [...])` →
  `HeroLaneOutcomeType` — confirmed via live schema introspection. But
  unlike `matchUp.with`, it only returns raw `matchCount`/`winCount`/
  `lossCount` for the laning phase, no precomputed TrueSynergy-style offset,
  so using it would mean a new ingestion table (`stratz_hero_lane_synergy`
  or similar) plus writing our own log5 expected-WR math for it — step-1
  (ingestion) scope, not step-2 (scoring). Deliberately not pulled in this
  pass since the user scoped the Phase 2 step 2 work to "Engine + API only."
  The blanket `stratz_hero_synergy.synergy` field is used as-is for now.
- **Stratz's `player.heroesPerformance` is capped at ~10 total matches under
  the default API token, regardless of the player's actual match count.**
  Confirmed against two very different accounts — the user's own public
  player (6,101 lifetime matches per Stratz's own `player.matchCount`) and
  an unrelated, very active public pro account (24,876 matches) — both
  capped identically at ~10 matches spread across 6-9 heroes. Not
  player-specific; a tier restriction on that aggregate endpoint
  specifically (`player.matches`, the raw per-match list, is *not* similarly
  capped — paginates fine up to `take: 100`/call — so full history is
  technically reachable, just not via the convenient pre-aggregated field).
  Per user decision, Phase 2 step 3 (`load_players.py`) uses **OpenDota
  only** for player history (`/players/{account_id}/heroes` is not capped
  this way and returns full lifetime per-hero stats) — Stratz was tried
  first (`load_stratz_players.py`), found broken for this purpose, and
  deleted along with its `stratz_player_hero_stats` table rather than kept
  with near-meaningless data. If a paid Stratz tier is added later, or the
  raw-match-pagination-and-aggregate-ourselves approach becomes worth the
  ~60+ paginated calls/player it'd take for an active player, revisit.
- **`players_id.txt` is the source of truth for who to pull and whether
  they're public**, parsed directly by `load_players.py` (regex on the
  `Name: account_id. Profile status: public|private.` format) — no
  duplicate CSV was created under `data/` for this, unlike `hero_role.csv`,
  since the source file already lives in a fixed, simple format. Re-run
  `load_players.py` after the user updates a player's status in that file
  to public.
- **Phase 2 step 4 — personal history is annotate-only, not a scoring
  signal.** Presented 3 options (blend into `total_advantage` like synergy,
  filter candidates to the player's hero pool, or annotate without
  affecting ranking); user picked annotate-only. Reason worth remembering:
  personal per-hero sample sizes are far noisier than the global data
  synergy/matchup already shrink — for the one public player loaded so far,
  median is 24 games/hero and 28/115 heroes have fewer than 10 games (min
  2) — two to three orders of magnitude smaller than the `stratz_hero_*`
  sample sizes `SHRINKAGE_K=500` was tuned against, so folding it into the
  score would need its own (probably much smaller) K and a baseline
  decision (self-relative log5 delta vs. global-hero-relative) that wasn't
  worth resolving for a first pass. `player_account_id` (optional, on
  `DraftRequest` and prompted once in `draft_suggester.py`) only attaches
  `player_history` (`games_played`/`wins`/`win_rate`) to each suggestion
  from `player_hero_stats` — ranking is untouched, identical to omitting
  it. If a blended version is wanted later, the shrinkage machinery already
  built for step 2 (`_shrink`, the `n/(n+K)` pattern) generalizes directly.

## Next up

- **Tests now exist, but only for `engine/draft_context.py`.** `tests/` +
  pytest (`pip install -e ".[dev]"`, then `pytest`) landed with Phase B —
  16 tests, no DB needed, since `build_context` is pure. Everything else
  (the matchup/draft engine, all API routers) is still spot-checked manually
  only. `draft_context.py` is deliberately split so scoring is pure and
  `load_bucket_stats` holds the only DB access — worth copying if the older
  engine code ever gets tests.
- `database_local.py` (a pre-reorg leftover with a real DB password and a
  live Stratz API JWT token) has been deleted and gitignored — if a copy
  surfaces again (e.g. from an old branch or backup), don't recommit it,
  and treat that Stratz token as compromised if it's ever found committed
  anywhere in history.
- King Arthas and Parma (`docs/players_id.txt`) are still marked private —
  no `player_hero_stats` for them yet. Once the user updates that file to
  public, re-run `load_players.py` and they'll show up in `GET /players`
  and the web UI's player selector automatically, no code changes needed.
