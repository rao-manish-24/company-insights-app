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

## Auth

Generate insights and the library require an account. Guests who hit **Generate insights** are prompted to **Sign in** or **Create account** (email + password, JWT). Each user’s briefs stay private to their account.

**Built-in admin** (ensured on every API start; override via env):

| | |
| --- | --- |
| Username | `admin` |
| Email | `admin@companyinsights.local` |
| Password | `Admin123!` |

Sign in with either the username or the email.

## Environment (minimum)

| Variable | Purpose |
| --- | --- |
| `JWT_SECRET` | Signs auth tokens (set a long random value in deploy) |
| `NEWS_API_KEY` | Live news (optional) |
| `LLM_API_KEY` | Live insights (optional) |
| `LLM_BASE_URL` / `LLM_MODEL` | e.g. xAI Grok |
| `RESEND_API_KEY` | Email on Render (SMTP blocked on free tier) |
| `EMAIL_TO` | Default inbox |

See `.env.example` for a full template.

---

## Deploy

Render Blueprint is configured in `render.yaml`.

1. Push to GitHub  
2. Render → **New → Blueprint** → this repo  
3. Set secrets on `companyinsights-api` (`JWT_SECRET`, `NEWS_API_KEY`, `LLM_API_KEY`, …)  
4. Set `VITE_API_BASE_URL=https://<api-host>/api` on `companyinsights-web`  
5. Set `CORS_ORIGINS` to the exact web origin  

---

## More detail

Full local runbook (architecture, API, rate limits, troubleshooting): `README.detailed.md`
