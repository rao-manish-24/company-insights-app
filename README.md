# Company Insights

**Partner-ready company news → insights in minutes.**

[![Live demo](https://img.shields.io/badge/demo-Render-46E3B7?style=flat-square)](https://companyinsights-web.onrender.com)
[![API](https://img.shields.io/badge/API-docs-009688?style=flat-square)](https://companyinsights-api.onrender.com/docs)
[![Stack](https://img.shields.io/badge/FastAPI-React-PostgreSQL-blue?style=flat-square)](#stack)

Type a company name. The app pulls recent public news and a company snapshot, then an LLM agent produces a structured brief: executive summary, themes, opportunities, risks, recommendations, and conversation starters — with source articles you can expand for a client conversation.

---

## Live demo

| | |
| --- | --- |
| **App** | https://companyinsights-web.onrender.com |
| **API docs** | https://companyinsights-api.onrender.com/docs |
| **Health** | https://companyinsights-api.onrender.com/api/health |

> **Note:** Render free tier sleeps when idle. The first request after a pause can take ~30–60 seconds while the API wakes up.

**Try:** `Microsoft`, `Nestlé`, `Siemens`, `Google`, `Bain & Company`  
Junk / non-company names should error instead of inventing a brief.

---

## Features

- Company autocomplete + resolve (Clearbit, Wikidata/Wikipedia, Yahoo, Fortune 500 roster)
- Validation that rejects gibberish and non-companies before spending LLM tokens
- Parallel news, profile, and market fetch
- LLM insights agent (OpenAI-compatible, e.g. xAI Grok) with offline heuristic fallback
- Dig-deeper expand on opportunities, risks, and recommendations
- Private guest sessions or signed-in accounts; per-user brief library
- Optional email brief via Resend
- Caching, rate limits, request coalescing, and upstream circuit breakers

---

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React · TypeScript · Vite · nginx |
| Backend | Python · FastAPI · SQLAlchemy · uvicorn |
| Database | PostgreSQL |
| Insights | OpenAI-compatible LLM |
| News | NewsAPI |
| Company data | Clearbit · Wikidata · Wikipedia · Yahoo Finance |
| Email | Resend |
| Infra | Docker · Docker Compose · Render |

---

## Quick start

```bash
cp .env.example .env
# set NEWS_API_KEY, LLM_API_KEY, JWT_SECRET as needed

docker compose up --build
```

| Service | URL |
| --- | --- |
| UI | http://localhost:3000 |
| API docs | http://localhost:8000/docs |
| Health | http://localhost:8000/api/health |

Without API keys, demo news + heuristic insights still work.

```bash
make up             # start stack
make health         # GET /api/health
make demo           # analyze Microsoft
make logs-backend
```

**Frontend hot reload** (API already on `:8000`):

```bash
cd frontend && npm install && npm run dev
# http://127.0.0.1:5173 — Vite proxies /api → localhost:8000
```

---

## Auth

| Mode | Behavior |
| --- | --- |
| Private session | Short-lived guest JWT; history for that session |
| Sign in / register | Email + password; briefs tied to the account |
| Email brief | Signed-in users only |

Default admin (created on API startup; override via env):

| | |
| --- | --- |
| Username | `admin` |
| Email | `admin@companyinsights.local` |
| Password | `Admin123!` |

Change `ADMIN_PASSWORD` and `JWT_SECRET` before any shared deploy.

---

## Environment

Minimum variables (see `.env.example` for the full list):

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Postgres URL |
| `JWT_SECRET` | Auth token signing key |
| `NEWS_API_KEY` | NewsAPI (optional) |
| `LLM_API_KEY` | LLM insights (optional) |
| `LLM_BASE_URL` / `LLM_MODEL` | e.g. `https://api.x.ai/v1` · `grok-4.5` |
| `CORS_ORIGINS` | Allowed web origins |
| `RESEND_API_KEY` / `EMAIL_TO` | Email briefs |

---

## Deploy on Render

1. Push to GitHub  
2. Render → **New → Blueprint** → this repo (`render.yaml`)  
3. Set API secrets: `JWT_SECRET`, `NEWS_API_KEY`, `LLM_API_KEY`, `ADMIN_PASSWORD`, `RESEND_*`, …  
4. Set `CORS_ORIGINS` to your static site URL  
5. Set `VITE_API_BASE_URL=https://<api-host>/api` on the web service and redeploy  

More detail: [`docs/DEPLOY.md`](./docs/DEPLOY.md) · [`README.detailed.md`](./README.detailed.md)

---

## Repo layout

```text
backend/      FastAPI, services, tests, Dockerfile
frontend/     React SPA + nginx Dockerfile
docs/         Deploy notes and assessment write-ups
docker-compose.yml
render.yaml
```

---

## License

Prototype for evaluation. Third-party APIs are subject to their own terms and free-tier limits. Never commit `.env` or secrets.
