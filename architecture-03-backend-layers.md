# Architecture 03 — Backend Layers, Frontend Tree, Data Model, API

---

## 1. Backend package layers

```mermaid
flowchart TB
  subgraph Edge["Edge"]
    Main["main.py<br/>lifespan create_all · CORS · middleware"]
    Routes["api/routes.py"]
  end

  subgraph Core["core/"]
    Config["config.py settings"]
    DB["database.py engine/session"]
    Deps["deps.py DI factories"]
    RL["rate_limit.py<br/>sliding window · singleflight"]
    MW["middleware.py X-Request-ID"]
    Exc["exceptions.py AppError"]
  end

  subgraph Services["services/"]
    AS["analysis_service.py"]
    NS["news_service.py"]
    PS["company_profile_service.py"]
    MS["market_data_service.py"]
    IA["insights_agent.py"]
    ES["email_service.py"]
  end

  subgraph Data["data"]
    Repo["repositories/analysis_repository.py"]
    ORM["models/company.py"]
    Sch["models/schemas.py"]
  end

  Main --> Routes
  Routes --> Deps
  Routes --> RL
  Routes --> AS
  Routes --> ES
  AS --> NS
  AS --> PS
  AS --> MS
  AS --> IA
  AS --> Repo
  ES --> Repo
  Repo --> ORM
  Routes --> Sch
```

**Note:** `alembic` is listed in requirements but there is no migration tree. Schema is created via `Base.metadata.create_all` plus a small `company_profile` column patch at startup.

---

## 2. Frontend component tree

```mermaid
flowchart TB
  Main["main.tsx"] --> App["App.tsx"]
  App --> Hook["useCompanyInsights"]
  Hook --> API["api.ts → /api"]
  App --> Progress["AnalysisProgress"]
  App --> Lib["Library aside<br/>Last 15 · Clear"]
  App --> Panel["InsightsPanel"]
  Panel --> Drill["InsightDrillModal"]
  Panel --> Email["EmailBriefForm"]
  Panel --> Match["utils/matchSources.ts"]
```

| File | Role |
| --- | --- |
| `App.tsx` | Hero search, status/progress, library chrome |
| `useCompanyInsights.ts` | analyze / open / history / clear / runMetrics |
| `AnalysisProgress.tsx` | % bar, stages, elapsed, token explanation |
| `InsightsPanel.tsx` | Full brief document + refresh + dig triggers |
| `InsightDrillModal.tsx` | Standard + deep expand UI (portal to body) |
| `EmailBriefForm.tsx` | Email brief |
| `config.ts` | `API_BASE`, 120s timeout |
| `vite.config.ts` / `nginx.conf` | `/api` proxy |

---

## 3. API catalog

```mermaid
flowchart LR
  subgraph Read
    H[GET /health]
    L[GET /analyses]
    G[GET /analyses/id]
    S[GET /analyses/search]
  end

  subgraph Write
    A[POST /analyze]
    E[POST /analyses/id/expand]
    M[POST /analyses/id/email]
    D[DELETE /analyses]
  end
```

| Method | Path | Service entry | Used by UI |
| --- | --- | --- | --- |
| GET | `/api/health` | DB `SELECT 1` | healthchecks |
| POST | `/api/analyze` | `AnalysisService.analyze` | Generate / Refresh |
| GET | `/api/analyses` | `list_recent` | Last 15 |
| GET | `/api/analyses/{id}` | `get_by_id` | Library reopen |
| DELETE | `/api/analyses` | `clear_history` | Clear history |
| GET | `/api/analyses/search` | `search` | **No** |
| POST | `/api/analyses/{id}/expand` | `expand_insight` | Dig modal |
| POST | `/api/analyses/{id}/email` | `EmailService` | Email form |

---

## 4. Data model — `company_analyses`

```mermaid
erDiagram
  COMPANY_ANALYSES {
    int id PK
    string company_name
    string company_name_normalized
    text executive_summary
    jsonb key_themes
    jsonb opportunities
    jsonb risks
    jsonb recommendations
    jsonb conversation_starters
    jsonb articles
    jsonb company_profile
    string llm_model
    timestamptz created_at
  }
```

### `company_profile` logical shape

```text
{
  founded, headquarters, employees, parent,
  revenue, operating_income, total_assets,
  key_people: [{ role, name }],
  source, url, matched_label,
  market: {
    ticker, exchange, currency,
    price, change, change_percent,
    market_cap, pe_ratio, sector, industry, ...
  }
}
```

### Not stored in Postgres

- Expand dig-deeper payloads (client memory only)
- Analyze response metrics (`elapsed_ms`, token counts)
- In-memory news TTL cache
- Rate-limit / singleflight maps (process-local)

---

## 5. Cross-cutting controls

```mermaid
flowchart TB
  Req[Incoming request] --> MW[Request ID + timing middleware]
  MW --> CORS[CORS allowlist]
  CORS --> Route{Route}
  Route -->|uncached analyze| IPRL[IP sliding-window limiter]
  Route -->|force_refresh| Cooldown[Per-company refresh cooldown]
  IPRL --> SF[singleflight coalesce]
  Cooldown --> SF
  SF --> Pipeline[Upstream pipeline]
```

| Control | Scope | Notes |
| --- | --- | --- |
| Analyze rate limit | Client IP | Cache hits exempt |
| Refresh cooldown | Normalized company | Default 5 minutes in config |
| Singleflight | Normalized company | Dedupes concurrent identical runs |
| News cache | Process memory | `NEWS_CACHE_MINUTES` |
| Analysis cache | Postgres rows | `ANALYSIS_CACHE_HOURS` |
| Auth | **None** | Open prototype — DELETE clears all |

---

## 6. LLM usage attachment

```mermaid
flowchart LR
  Call["chat.completions.create"] --> Usage["_extract_usage(response.usage)"]
  Usage --> Attach["insights['_usage']"]
  Attach --> Pop["AnalysisService pops _usage"]
  Pop --> Resp["CompanyAnalysisResponse<br/>prompt_tokens · completion_tokens · total_tokens · elapsed_ms"]
  Resp --> UI["AnalysisProgress"]
```

If the gateway omits usage, the agent estimates tokens from prompt/content length so the UI still shows a signal.

---

## 7. Security / ops diagram notes

```mermaid
flowchart TB
  Secrets[".env / Render sync:false<br/>NEWS · LLM · RESEND · SMTP · DATABASE"] --> API
  API["FastAPI"] --> Quotas["Rate limits + caches<br/>protect NewsAPI / LLM"]
  API --> Open["No user auth<br/>treat as trusted-network prototype"]
```

Production hardening (not implemented): authn/z, shared Redis rate limits across instances, soft-delete history, per-tenant isolation.
