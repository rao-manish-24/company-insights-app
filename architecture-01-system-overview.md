# Architecture 01 — System Overview

**Company Insights** turns a company name into a partner-ready brief: recent news, Wikidata profile, Yahoo market snapshot, LLM synthesis, optional email, and a dig-deeper expand path.

Source of truth: `docker-compose.yml`, `render.yaml`, `backend/app/*`, `frontend/src/*`.

---

## 1. Runtime topology (local Docker)

```mermaid
flowchart TB
  Partner["Partner browser"]

  subgraph Compose["docker-compose"]
    Nginx["frontend nginx<br/>:3000 → :80<br/>SPA + /api proxy"]
    API["backend FastAPI<br/>uvicorn :8000"]
    DB[("PostgreSQL 16<br/>:5432<br/>companyinsights")]
  end

  subgraph Externals["Server-side externals only"]
    News["NewsAPI<br/>/v2/everything"]
    Wiki["Wikidata API"]
    Yahoo["Yahoo Finance search/chart<br/>+ yfinance"]
    LLM["LLM gateway<br/>OpenAI-compatible"]
    Mail["Resend HTTPS<br/>or SMTP"]
  end

  Partner -->|HTTP| Nginx
  Nginx -->|"/api/*"| API
  API --> DB
  API --> News
  API --> Wiki
  API --> Yahoo
  API --> LLM
  API --> Mail
```

**Dev alternate:** Vite `:5173` proxies `/api` → `localhost:8000` (same backend contracts).

---

## 2. Runtime topology (Render production)

```mermaid
flowchart TB
  Partner["Partner browser"]
  Web["Static site<br/>companyinsights-web.onrender.com<br/>Vite dist"]
  API["Docker web service<br/>companyinsights-api.onrender.com"]
  DB[("Render Postgres<br/>companyinsights-db")]

  subgraph Upstream["Upstreams"]
    XAI["xAI · api.x.ai<br/>model grok-4.5"]
    News["NewsAPI"]
    Wiki["Wikidata"]
    Yahoo["Yahoo / yfinance"]
    Resend["Resend emails"]
  end

  Partner --> Web
  Web -->|"VITE_API_BASE_URL<br/>HTTPS /api"| API
  API --> DB
  API --> XAI
  API --> News
  API --> Wiki
  API --> Yahoo
  API --> Resend
```

| Difference | Local Compose | Render |
| --- | --- | --- |
| UI hosting | nginx container, same-origin `/api` | Static site, cross-origin API |
| DB | `postgres:16-alpine` | Managed Postgres |
| LLM default | `.env` (`LLM_*`) | `https://api.x.ai/v1` · `grok-4.5` |
| Email | Resend or SMTP | Prefer Resend (SMTP often blocked) |
| Quotas | Looser defaults | Stricter cache / rate / article caps |

---

## 3. Logical layer boundaries

```mermaid
flowchart TB
  subgraph Presentation["Presentation"]
    React["React 19 App<br/>hooks · components · api.ts"]
  end

  subgraph Edge["API edge"]
    FastAPI["FastAPI /api router<br/>CORS · X-Request-ID · rate limit"]
  end

  subgraph Application["Application services"]
    Analysis["AnalysisService"]
    NewsS["NewsService"]
    ProfileS["CompanyProfileService"]
    MarketS["MarketDataService"]
    Agent["InsightsAgent"]
    EmailS["EmailService"]
  end

  subgraph Persistence["Persistence"]
    Repo["AnalysisRepository"]
    ORM["SQLAlchemy CompanyAnalysis"]
    PG[("company_analyses")]
  end

  React --> FastAPI
  FastAPI --> Analysis
  FastAPI --> EmailS
  Analysis --> NewsS
  Analysis --> ProfileS
  Analysis --> MarketS
  Analysis --> Agent
  Analysis --> Repo
  EmailS --> Repo
  Repo --> ORM --> PG
```

---

## 4. External dependency map

| Dependency | Service file | Protocol | Auth |
| --- | --- | --- | --- |
| NewsAPI | `news_service.py` | REST GET | `NEWS_API_KEY` |
| Wikidata | `company_profile_service.py` | MediaWiki API | none |
| Yahoo Finance + yfinance | `market_data_service.py` | HTTP + Python lib | none |
| LLM (OpenAI SDK) | `insights_agent.py` | chat.completions JSON | `LLM_API_KEY` |
| Resend | `email_service.py` | HTTPS POST | `RESEND_API_KEY` |
| SMTP | `email_service.py` | smtplib | SMTP_* |
| PostgreSQL | `database.py` / repository | SQLAlchemy | `DATABASE_URL` |

Demo / fallback: missing news key → demo articles; missing/failing LLM → `fallback-heuristic` brief.

---

## 5. Key file anchors

| Concern | Path |
| --- | --- |
| Compose | `docker-compose.yml` |
| Render | `render.yaml` |
| App factory | `backend/app/main.py` |
| Routes | `backend/app/api/routes.py` |
| Orchestration | `backend/app/services/analysis_service.py` |
| LLM | `backend/app/services/insights_agent.py` |
| Frontend shell | `frontend/src/App.tsx` |
| API client | `frontend/src/api.ts` |
| nginx proxy | `frontend/nginx.conf` |
