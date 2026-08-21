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
- [x] **[TOGETHER]** UFW enabled: allow 22/tcp (SSH) and 80/tcp (HTTP), deny
      everything else inbound. Verified SSH still reachable after enabling
      before moving on. 443/tcp not opened yet — add it if/when TLS is set up.

## Phase 2 — Migrate the database

- [ ] **[YOU]** Have the Heroku Postgres connection string ready (already in
      your gitignored `config.py`).
- [ ] **[TOGETHER]** `pg_dump` from Heroku, restore into the VPS's Postgres.
      I can write and run the exact commands with you, or write a script for
      you to run yourself if you'd rather not paste prod DB credentials into
      chat.
- [ ] **[YOU]** Decide whether to keep Heroku Postgres around as a fallback
      for a while, or retire it once the migration is verified.

## Phase 3 — Deploy the frontend

- [ ] **[YOU]** Create a free Cloudflare Pages or Netlify account, connect it
      to the GitHub repo (or drag-and-drop the `web/` folder).
- [ ] **[ME]** Update `web/js/config.js`'s `API_BASE_URL` to the VPS's
      domain/IP once it exists.
- [ ] **[YOU/ME]** Trigger the deploy — auto-deploys on push if connected to
      GitHub.

## Phase 4 — Deploy the backend

- [ ] **[TOGETHER]** On the Droplet: clone the repo, copy `infra/.env.example`
      to `infra/.env` and fill in real values, then `docker compose -f
      infra/docker-compose.yml up -d --build`.

## Phase 5 — Verify and cut over

- [ ] **[TOGETHER]** Smoke test both pages against the production API.
- [ ] **[YOU]** Point any custom domain's DNS at the new hosts, if using one.
- [ ] **[YOU]** Decide when to fully decommission Heroku.
