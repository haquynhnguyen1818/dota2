# Progress / handoff notes

Read this first when starting a new session. `proj_obj.txt` has the spec;
this file has what's actually built, key decisions, and gotchas that aren't
obvious from the code alone.

## Status

- Steps 1-4 done. Step 5 (frontend) has two implementations: the original
  Streamlit dashboard (`src/app/dashboard/`, still present, no longer the
  primary UI) and a static HTML/CSS/vanilla-JS frontend (`web/`) that
  replaced it as of 2026-08-21 — see "Why the frontend changed" below.
  **Fully deployed and live**: `web/` on Cloudflare
  (`https://dota2.haquynh-nguyen.workers.dev`), API + Postgres on a
  DigitalOcean Droplet behind Caddy (`https://165-22-246-179.sslip.io`).
  Heroku Postgres has been migrated from and retired (add-on deleted) — see
  `docs/deploy_todo.md` for the full step-by-step history.

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
- `POST /draft-suggestions` — Objective 2, body `{"opponent_picks": [id,...]}`
  (1-5 ids, no dupes). Stateless: mirrors `draft_suggester.py`'s weighted-sum
  logic, but the caller resends the full accumulated pick list each call
  instead of the server holding session state.
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
  a CSS workaround for the same thing). Carry/Midlane/Offlane tabs, top-10
  best/worst lists with a WR column (green ≥50%) and a bar visualizing
  advantage magnitude. Rows are clickable — expands inline sub-rows (same
  list, not a separate table) showing each opponent's individual advantage,
  sorted descending server-side (`_build_suggestion` in
  `api/routers/draft.py`). Mobile gets a segmented best/worst toggle instead
  of the two-column grid.
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
  tier highlighting all confirmed working end-to-end).

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

- **Deployment.** Nothing is hosted yet. Direction decided (see "Why the
  frontend changed" above): no Streamlit Community Cloud, must be
  always-live with zero cold-start. Current plan: `web/` on a free
  static host (Cloudflare Pages/Netlify/GitHub Pages — genuinely $0 at this
  traffic level, no cold start) + `src/app/api/` on a small always-on VPS
  (Hetzner CX22 ~$4-5/mo, DigitalOcean/Linode ~$5-6/mo). Exact host still
  undecided. Remember to point `web/js/config.js`'s `API_BASE_URL` at the
  deployed API URL before publishing the static site.
- **`api/db.py` opens a fresh `psycopg.connect()` per request** (no pooling)
  — measured ~3.4s for a single `POST /draft-suggestions` call against the
  live Heroku Postgres DB. Not a bug, but worth fixing (e.g. a
  module-level connection pool) if the always-on host makes this feel slow
  in practice; the frontend's stale-response guard (see `web/` above) works
  around the *symptom* (race conditions from slow requests) but doesn't
  address the root latency.
- No automated tests exist yet for the engine or API logic (correctness
  has only been spot-checked manually/interactively so far, incl. live
  smoke tests of all 4 API endpoints against the real DB).
- `database_local.py` (a pre-reorg leftover with a real DB password and a
  live Stratz API JWT token) has been deleted and gitignored — if a copy
  surfaces again (e.g. from an old branch or backup), don't recommit it,
  and treat that Stratz token as compromised if it's ever found committed
  anywhere in history.
