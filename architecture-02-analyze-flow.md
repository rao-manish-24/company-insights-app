# Architecture 02 — Analyze, Expand, Email, Library Flows

Detailed request sequences for the four partner-facing workflows.

---

## 1. Analyze — happy path (uncached)

**Endpoint:** `POST /api/analyze`  
**Body:** `{ company_name, force_refresh?, send_email?, email_to? }`  
**UI:** Generate / Refresh → `useCompanyInsights.runAnalysis` → `api.analyzeCompany`

```mermaid
sequenceDiagram
  autonumber
  actor P as Partner
  participant UI as React App
  participant R as routes.analyze_company
  participant S as AnalysisService
  participant RL as rate_limit / singleflight
  participant N as NewsService
  participant PM as Profile ∥ Market
  participant L as InsightsAgent
  participant DB as AnalysisRepository
  participant E as EmailService

  P->>UI: Enter company / Generate
  UI->>R: POST /api/analyze
  R->>S: peek_cache (if !force_refresh)
  alt cache hit within ANALYSIS_CACHE_HOURS
    S-->>R: CompanyAnalysisResponse cached=true tokens=0
    R-->>UI: brief
  else cache miss
    R->>RL: analyze-ip:{client} sliding window
    R->>S: analyze(name, force_refresh)
    opt force_refresh
      S->>RL: refresh:{normalized} cooldown
    end
    S->>RL: singleflight analyze:{normalized}
    S->>N: fetch_company_news
    N-->>S: articles[]
    par Profile and market
      S->>PM: CompanyProfileService.fetch_profile
      S->>PM: MarketDataService.fetch_market
    end
    PM-->>S: profile + market
    S->>S: apply_to_profile
    S->>L: analyze(name, articles, profile)
    L-->>S: insights + _usage + leadership_fill
    S->>DB: save(CompanyAnalysis)
    DB-->>S: row with id
    S-->>R: response + elapsed_ms + token fields
    opt send_email or EMAIL_AUTO_SEND
      R->>E: send_analysis_async
    end
    R-->>UI: brief
    UI->>UI: AnalysisProgress shows timing + tokens
  end
```

### Parallelism inside `_analyze_uncached`

```mermaid
flowchart LR
  A[Start uncached] --> B[NewsService]
  B --> C{asyncio.gather}
  C --> D[Wikidata profile<br/>to_thread]
  C --> E[Yahoo / yfinance<br/>to_thread]
  D --> F[Merge market into profile]
  E --> F
  F --> G[InsightsAgent.analyze<br/>to_thread]
  G --> H[Merge leadership_fill]
  H --> I[repo.save]
  I --> J[Attach metrics<br/>elapsed · tokens]
```

### Cache / rate-limit policy

| Condition | Rate limit | Upstream calls | Tokens returned |
| --- | --- | --- | --- |
| Cache hit (`!force_refresh`) | Skipped | None | `0` |
| Fresh analyze | IP window applied | News + profile + market + LLM | Real usage |
| Refresh under cooldown + non-fallback cache | May serve cache | None | `0` |
| Refresh under cooldown + fallback brief | Allowed to re-run | Full pipeline | Real usage |

---

## 2. Dig-deeper expand

**Endpoint:** `POST /api/analyses/{analysis_id}/expand`  
**Body:** `{ kind: opportunity\|risk\|recommendation, index, depth: standard\|deep, prior_analysis? }`

```mermaid
sequenceDiagram
  autonumber
  actor P as Partner
  participant Panel as InsightsPanel
  participant Modal as InsightDrillModal
  participant R as routes.expand_insight
  participant S as AnalysisService.expand_insight
  participant L as InsightsAgent.expand_item
  participant DB as AnalysisRepository

  P->>Panel: Click opportunity / risk / recommendation
  Panel->>Modal: open drill
  P->>Modal: Ask more (standard)
  Modal->>R: POST .../expand depth=standard
  R->>S: expand_insight
  S->>DB: get_by_id
  S->>S: pick item by kind+index
  S->>L: expand_item + match sources
  L-->>S: ExpandInsightResponse
  S-->>Modal: analysis + questions + moves + sources
  opt Dig deeper again
    P->>Modal: deep dig
    Modal->>R: POST .../expand depth=deep + prior_analysis
    R->>S->>L: deep narrative + spotlight_points
    L-->>Modal: deep payload
  end
```

**Not persisted.** Client caches expand payloads in React state. No IP rate limit on expand today.

| Depth | Fields |
| --- | --- |
| `standard` | `deeper_analysis`, `why_it_matters`, `questions_to_ask`, `suggested_moves`, `sources` |
| `deep` | `detailed_narrative`, `spotlight_points`, `sources` |

---

## 3. Email brief

```mermaid
flowchart TB
  A["EmailBriefForm<br/>or analyze send_email"] --> B["POST /api/analyses/{id}/email<br/>or analyze path"]
  B --> C[EmailService.send_analysis]
  C --> D{RESEND_API_KEY?}
  D -->|yes| E[POST api.resend.com/emails]
  D -->|no| F{SMTP configured?}
  F -->|yes| G[smtplib TLS/SSL]
  F -->|no| H[EmailServiceError → 502]
  C --> I[Build HTML + text from CompanyAnalysis]
  I --> D
```

- Explicit UI email failures surface to the client.
- `EMAIL_AUTO_SEND` failures are logged only (analyze still succeeds).

---

## 4. Library / history

```mermaid
flowchart LR
  UI[Library aside] -->|Last 15| L["GET /api/analyses?limit=15"]
  UI -->|click row| O["GET /api/analyses/{id}"]
  UI -->|Clear history| C["DELETE /api/analyses"]
  API["GET /api/analyses/search"] -.->|API only| S[ILIKE normalized name]
```

“Last 15” is a **max**, not a fill. If fewer rows exist, fewer are shown.

---

## 5. Frontend state machine (analyze)

```mermaid
stateDiagram-v2
  [*] --> Idle
  Idle --> Loading: runAnalysis / openRecent
  Loading --> Ready: 200 + setAnalysis + setRunMetrics
  Loading --> Error: ApiError
  Ready --> Loading: Generate / Refresh / open another
  Error --> Loading: retry
  Ready --> Idle: clearHistory (optional)
```

`AnalysisProgress` reads `loading` + `runMetrics` (elapsed, prompt/completion/total tokens, cached).
