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

export interface KeyPerson {
  role: string
  name?: string | null
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
}

export interface AnalysisListItem {
  id: number
  company_name: string
  executive_summary: string
  created_at: string
}
