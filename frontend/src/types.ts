export interface NewsArticle {
  title: string
  description?: string | null
  source?: string | null
  url?: string | null
  published_at?: string | null
}

export interface ThemeInsight {
  theme: string
  insight: string
  evidence?: string[]
}

export interface Opportunity {
  title: string
  detail: string
  priority?: string
  sources?: string[]
  evidence?: string[]
}

export interface Risk {
  title: string
  detail: string
  severity?: string
  sources?: string[]
  evidence?: string[]
}

export interface Recommendation {
  action: string
  rationale: string
  sources?: string[]
  evidence?: string[]
}

export type ExpandInsightKind = 'opportunity' | 'risk' | 'recommendation'

export interface ExpandInsightSource {
  title: string
  source?: string | null
  url?: string | null
  published_at?: string | null
  description?: string | null
}

export interface SpotlightPoint {
  point: string
  explanation: string
}

export interface ExpandInsightResult {
  kind: ExpandInsightKind
  index: number
  depth?: 'standard' | 'deep'
  heading: string
  deeper_analysis: string
  why_it_matters: string
  questions_to_ask: string[]
  suggested_moves: string[]
  detailed_narrative?: string | null
  spotlight_points?: SpotlightPoint[]
  sources: ExpandInsightSource[]
  fallback?: boolean
}

export interface KeyPerson {
  role: string
  name?: string | null
}

export interface MarketSnapshot {
  ticker?: string | null
  name?: string | null
  exchange?: string | null
  currency?: string | null
  price?: string | null
  previous_close?: string | null
  change_percent?: string | null
  market_cap?: string | null
  pe_ratio?: string | null
  forward_pe?: string | null
  eps?: string | null
  dividend_yield?: string | null
  fifty_two_week_high?: string | null
  fifty_two_week_low?: string | null
  beta?: string | null
  sector?: string | null
  industry?: string | null
  volume?: string | null
  avg_volume?: string | null
  source?: string | null
  source_url?: string | null
}

export interface CompanyProfile {
  founded?: string | null
  headquarters?: string | null
  employees?: string | null
  parent_company?: string | null
  revenue?: string | null
  operating_income?: string | null
  total_assets?: string | null
  key_people?: KeyPerson[]
  source?: string | null
  source_url?: string | null
  matched_label?: string | null
  market?: MarketSnapshot | null
}

export interface CompanyAnalysis {
  id: number
  company_name: string
  executive_summary: string
  key_themes: ThemeInsight[]
  opportunities: Opportunity[]
  risks: Risk[]
  recommendations: Recommendation[]
  conversation_starters: string[]
  articles: NewsArticle[]
  company_profile?: CompanyProfile
  llm_model: string
  created_at: string
  cached?: boolean
  elapsed_ms?: number | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  total_tokens?: number | null
}

export interface AnalysisRunMetrics {
  elapsedMs: number
  promptTokens: number | null
  completionTokens: number | null
  totalTokens: number | null
  cached: boolean
}

export interface AnalysisListItem {
  id: number
  company_name: string
  executive_summary: string
  created_at: string
}
