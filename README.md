# Company Insights

Partner-ready company news → insights in minutes.

Enter a company name. The app pulls recent public news, builds a company snapshot (leadership, HQ, financials), and generates a structured brief: summary, themes, opportunities, risks, recommendations, and conversation starters.

**Stack:** FastAPI · React · PostgreSQL · Docker · LLM (OpenAI-compatible) · NewsAPI · Resend/Wikidata

---

## Live demo

| | |
| --- | --- |
| **App** | https://companyinsights-web.onrender.com |
| **API docs** | https://companyinsights-api.onrender.com/docs |
| **Health** | https://companyinsights-api.onrender.com/api/health |

---

## Quick start (local)

```bash
# create a local .env with your free-tier keys, then:
docker compose up --build
```

- UI: http://localhost:3000  
- API: http://localhost:8000/docs  

Without keys, demo news + heuristic insights still work.

---

## Useful commands

```bash
make up        # start stack
make health    # check API
make demo      # analyze Microsoft
make logs-backend
```

---

## Environment (minimum)

| Variable | Purpose |
| --- | --- |
| `NEWS_API_KEY` | Live news (optional) |
| `LLM_API_KEY` | Live insights (optional) |
| `LLM_BASE_URL` / `LLM_MODEL` | e.g. xAI Grok |
| `RESEND_API_KEY` | Email on Render (SMTP blocked on free tier) |
| `EMAIL_TO` | Default inbox |

---

## Deploy

Render Blueprint is configured in `render.yaml`.

1. Push to GitHub  
2. Render → **New → Blueprint** → this repo  
3. Set secrets on `companyinsights-api`  
4. Set `VITE_API_BASE_URL=https://<api-host>/api` on `companyinsights-web`  
5. Set `CORS_ORIGINS` to the exact web origin  

---

## More detail

Full local runbook (architecture, API, rate limits, troubleshooting): `README.detailed.md`
