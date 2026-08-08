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
}

export interface Risk {
  title: string
  detail: string
  severity?: string
}

export interface Recommendation {
  action: string
  rationale: string
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
  llm_model: string
  created_at: string
  cached?: boolean
}

export interface AnalysisListItem {
  id: number
  company_name: string
  executive_summary: string
  created_at: string
}
