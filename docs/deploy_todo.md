# Deployment todo

Supersedes `deploy_plan.md` on two points (see notes there / chat history):
Railway's Singapore region needs the $20/mo Pro plan, not the $5/mo Hobby
plan; decided to use a Singapore VPS instead. `web/` has no build step, so
there's no `NEXT_PUBLIC_API_URL`/`VITE_API_URL` — the API URL is a plain
constant in `web/js/config.js`.

**Target setup:** `web/` static frontend on a free CDN host (Cloudflare
Pages/Netlify) + FastAPI and Postgres both on one small DigitalOcean
Droplet in the Singapore (SGP1) region (~$6/mo Basic tier) — co-locating
API and DB avoids any cross-region hop between them. Both run via Docker
Compose (`infra/docker-compose.yml`).

Tags: **[YOU]** = needs your account/payment/credentials, I can't do it.
**[ME]** = code change, I can do it now. **[TOGETHER]** = needs your
credentials/access but I can drive it once you provide them in-session.

## Phase 0 — Code prep (do before any infra exists)

- [x] **[ME]** Add DB connection pooling to `src/app/api/db.py`
      (`psycopg_pool.ConnectionPool`, opened/closed via FastAPI's lifespan in
      `main.py`) — was a fresh `psycopg.connect()` per request (~3.4s
      measured against the Europe-hosted Heroku Postgres); pooled it's a
      stable ~1.1-1.4s from this dev machine (remaining time is real query +
      network RTT to Europe, which the VPS+DB co-location in Phase 2 fixes).
      Verified with a headless-browser test hitting the live API through
      both frontend pages, all still passing.
- [x] **[ME]** Move DB credentials in `src/app/api/db.py` to
      `DB_HOST`/`DB_PORT`/`DB_USER`/`DB_PASSWORD`/`DB_NAME`/`DB_SSLMODE` env
      vars, falling back to `src/app/config.py`'s `creds_opendota` for local
      dev when those aren't set (that file stays gitignored either way —
      production reads env vars only, never touches it).
- [x] **[ME]** CORS in `src/app/api/main.py` now reads `ALLOWED_ORIGINS`
      (comma-separated) from the environment, falling back to `["*"]` when
      unset — set it once the frontend domain is live (Phase 3).
- [x] **[ME]** Added `infra/docker-compose.yml` + `infra/docker/api.Dockerfile`
      (api + postgres, matching the earlier `proj_folder_structure.md`
      sketch) and `infra/.env.example` (copy to `infra/.env`, gitignored,
      for `DB_USER`/`DB_PASSWORD`/`DB_NAME`/`ALLOWED_ORIGINS`). `db`'s 5432
      isn't published to the host by default (only the `api` container can
      reach it) — temporarily add a `ports:` mapping if you need external
      `psql` access, e.g. during the Phase 2 restore.
      **Not build-tested** — no Docker available in this dev environment;
      needs a real `docker compose build` once Docker exists (VPS, or your
      own machine if you have Docker Desktop) before trusting it fully.

## Phase 1 — Provision the VPS

- [x] **[YOU]** Created a DigitalOcean account and Droplet
      (`ubuntu-s-1vcpu-1gb-sgp1-202608`, Ubuntu 24.04 plain image — not the
      Docker Marketplace image, so it needed a manual install).
- [x] **[TOGETHER]** SSH access: root login was already `PermitRootLogin yes`;
      needed a dedicated passphrase-less key (`~/.ssh/do_dota2_deploy` on the
      dev machine, `dota2-deploy-automation` in the Droplet's
      `authorized_keys`) since the personal key on this machine has a
      passphrase this non-interactive shell can't supply. Installed Docker
      via `get.docker.com` (had to wait out an `unattended-upgrades` dpkg
      lock first, common on a freshly-booted Droplet). Confirmed: Docker
      29.7.2, Compose v5.5.0.
- [x] **[TOGETHER]** UFW enabled: allow 22/tcp (SSH), 80/tcp (HTTP), and
      443/tcp (HTTPS, added in Phase 3 for Caddy). Verified SSH still
      reachable after enabling before moving on.

## Phase 2 — Migrate the database

- [x] **[TOGETHER]** `pg_dump`'d Heroku (12 tables, ~55k rows total) and
      restored into the Droplet's `db` container via `docker compose exec -T
      db psql`. Heroku's actual server version is Postgres 18.3 (not 16 as
      assumed) — Ubuntu 24.04's default `pg_dump` is v16 and refuses to dump
      a newer server, so had to add the official PGDG apt repo and install
      `postgresql-client-18` first. One harmless restore error
      (`unrecognized configuration parameter "transaction_timeout"` — a
      PG17+ session setting pg_dump 18 emits automatically; PG16 doesn't
      have it, no schema/data impact). Row counts verified identical on
      both sides for all 12 tables before treating this as done.
- [x] Confirmed the point of this exercise: same query
      (`POST /draft-suggestions`, 2 opponent picks) went from ~1.1-1.4s
      against Heroku-over-the-internet (already down from ~3.4s pre-pooling)
      to **~10ms** now that the DB is co-located with the API on the Droplet.
- [ ] **[YOU]** Decide whether to keep Heroku Postgres around as a fallback
      for a while, or retire it now that the migration is verified working.

## Phase 3 — Deploy the frontend

- [x] **[YOU]** Created a Cloudflare account, connected the GitHub repo.
      First deploy failed: Cloudflare built from the repo root, found
      `pyproject.toml`, and tried `pip install .` (wrong Python version too —
      Cloudflare's build image has 3.13, we require >=3.14) instead of just
      serving `web/`. Fixed by setting **Root directory** to `web`, **Build
      command** empty, **Framework preset** None — `web/` has no build step
      at all, it's just served as-is. Live at
      `https://dota2.haquynh-nguyen.workers.dev` (Cloudflare's unified
      Workers/Pages platform — functionally a normal Pages static-site deploy).
- [x] **[ME]** HTTPS for the API: no custom domain, so used the free
      `sslip.io` wildcard-DNS trick (`165-22-246-179.sslip.io` resolves
      straight to the Droplet's IP) + Caddy as a reverse proxy in front of
      the `api` container — Caddy auto-provisions and renews a real Let's
      Encrypt cert for that hostname with zero manual cert management.
      Necessary because Cloudflare serves the frontend over HTTPS, and
      browsers block HTTPS pages from calling a plain-HTTP API ("mixed
      content") — the API had to be HTTPS too, not just reachable.
- [x] **[ME]** `web/js/config.js` now auto-detects local dev
      (`localhost`/`127.0.0.1`) vs. production, pointing at
      `https://165-22-246-179.sslip.io` in the deployed site. `ALLOWED_ORIGINS`
      on the Droplet tightened from `["*"]` to the real
      `https://dota2.haquynh-nguyen.workers.dev` origin.
- [x] Committed and pushed everything from this session (it had never been
      pushed before this point) — Cloudflare auto-deploys on push. Watched
      out for Cloudflare's edge-cache propagation lag (new deploys can serve
      inconsistently across POPs for ~1-2 min before settling globally).

## Phase 4 — Deploy the backend

- [x] **[TOGETHER]** Cloned the repo onto the Droplet, `infra/.env` filled
      with a freshly-generated DB password (not reused from Heroku),
      `docker compose -f infra/docker-compose.yml up -d --build`. Image
      includes `streamlit` as an unused dependency (still in
      `pyproject.toml` since the old dashboard hasn't been removed) — harmless,
      just a few extra MB in the image.

## Phase 5 — Verify and cut over

- [x] **[TOGETHER]** Full production smoke test: real headless-browser run
      against the live `https://dota2.haquynh-nguyen.workers.dev` calling the
      live `https://165-22-246-179.sslip.io` API — both pages load real data,
      zero console/network errors, no CORS or mixed-content issues.
- [ ] **[YOU]** No custom domain in use (by choice) — nothing to point DNS
      at. Revisit if a real domain gets added later.
- [x] **[YOU]** Decided: retired Heroku. Add-on deleted from the Heroku
      dashboard on 2026-08-21. Local dev's `config.py` fallback repointed at
      the Droplet's Postgres via SSH tunnel (loopback-only port bind added
      to `infra/docker-compose.yml`) instead of the now-gone Heroku host —
      see `docs/progress.md`'s "What's running" for the tunnel command.
      `ingestion`/`engine` scripts' hardcoded `sslmode="require"` also
      switched to read from `creds_opendota` (default still `"require"`),
      since the tunneled connection needs `"disable"` instead.
