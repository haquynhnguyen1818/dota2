## Updated folder structure

```
project-root/
├── pyproject.toml
├── src/
│   └── app/
│       ├── ingestion/            # step 1: pull from APIs
│       │   ├── clients/            # one client module per external API
│       │   └── jobs.py             # entrypoint(s) for scheduled pulls
│       ├── processing/           # step 2: transform + load
│       │   └── jobs.py
│       ├── engine/               # step 3: calculation engine
│       │   ├── core.py
│       │   └── models.py           # pydantic/dataclass domain models (not DB models)
│       ├── api/                  # step 4: FastAPI app
│       │   ├── main.py
│       │   ├── routers/
│       │   └── schemas/            # request/response models
│       ├── dashboard/            # step 5: Streamlit app
│       │   ├── Home.py             # Streamlit entrypoint
│       │   ├── pages/              # multi-page app, one file per page
│       │   ├── components/         # reusable widgets/charts
│       │   └── api_client.py       # thin wrapper calling step 4's API
│       ├── db/                   # shared across 1-4
│       │   ├── models.py           # SQLAlchemy models
│       │   └── session.py
│       └── config.py             # env vars, settings
│
├── alembic/                      # DB migrations
├── tests/
│   ├── ingestion/
│   ├── processing/
│   ├── engine/
│   ├── api/
│   └── dashboard/                # optional — Streamlit tests are often thin/skipped
│
├── infra/
│   ├── docker-compose.yml           # db + api + dashboard for local dev
│   └── docker/
│       ├── api.Dockerfile
│       └── dashboard.Dockerfile
│
├── scripts/
│   ├── run_ingestion.py
│   └── run_processing.py
│
└── README.md
```

## What changed, and why

**`web/` is gone; `dashboard/` lives inside `src/app/`.** Everything is one Python package now, one `pyproject.toml`, one dependency set, one virtualenv. That's the main win of going this route for a small project — there's no contract-drift risk between frontend and backend types because there's no second language at all.

**`dashboard/api_client.py` — one important design decision to make deliberately: should the dashboard call the FastAPI service over HTTP, or should it import `engine`/`db` directly and skip the API layer?**

Both are valid here, worth picking on purpose rather than by default:

- **Call the API over HTTP** (`requests`/`httpx` inside `api_client.py`) — keeps the API layer honest as the single real entrypoint to your data (useful if you expect other consumers of step 4's API besides this dashboard, or want to deploy the dashboard and API as separate processes/containers that scale independently).
- **Import `engine`/`db` directly**, skip HTTP — less latency, one fewer moving part, simpler local dev. Reasonable if the dashboard is the *only* consumer and step 4's API mainly exists for future-proofing or external access.

Given you're already building step 4 as a real API, I'd lean toward the dashboard calling it over HTTP even though it costs a bit of latency — it keeps the API layer honest as the single source of truth. If in practice you find yourself frequently reaching past the API into `db`/`engine` directly from the dashboard "just this once," that's a sign to reconsider and let the dashboard import directly instead.

**Docker split**: `api.Dockerfile` and `dashboard.Dockerfile` stay separate even though they share one codebase, since `streamlit run` and `uvicorn` are two different long-running processes you'll likely want scaled/restarted independently. `docker-compose.yml` ties db + api + dashboard together for local dev with one command.

**Multi-page Streamlit**: the `pages/` folder is Streamlit's own convention (auto-detected for the sidebar nav) — worth following exactly as Streamlit expects rather than customizing, same reasoning as before with Java/`pom.xml` conventions.

One thing worth deciding now rather than later: do steps 1–2 (ingestion/processing) run as cron-triggered one-off scripts, or does the dashboard need to trigger a manual refresh on demand? If the latter, you'd want `dashboard/` to be able to kick off `ingestion`/`processing` jobs directly (or via the API), which is worth wiring up early rather than retrofitting.