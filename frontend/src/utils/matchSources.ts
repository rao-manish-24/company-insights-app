import type { NewsArticle } from '../types'

type SourceableItem = {
  title?: string
  action?: string
  detail?: string
  rationale?: string
  sources?: string[]
  evidence?: string[]
}

export function matchSources(
  item: SourceableItem,
  articles: NewsArticle[],
  limit = 4,
): NewsArticle[] {
  const cues = [...(item.sources || []), ...(item.evidence || [])].map(String)
  const blob = `${item.title || item.action || ''} ${item.detail || item.rationale || ''}`.toLowerCase()

  const scored = articles
    .map((article, index) => {
      const title = (article.title || '').toLowerCase()
      const source = (article.source || '').toLowerCase()
      let score = 0

      for (const cue of cues) {
        const cueL = cue.toLowerCase()
        if (cueL.includes(`[${index + 1}]`) || cueL.trim() === String(index + 1)) score += 8
        if (title && (title.includes(cueL) || cueL.includes(title))) score += 6
        if (source && cueL.includes(source)) score += 2
      }

      const tokens = title.match(/[a-z0-9]{4,}/g) || []
      const overlap = tokens.filter((token) => blob.includes(token)).length
      if (overlap >= 2) score += overlap

      return { article, score }
    })
    .filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((row) => row.article)

  if (scored.length > 0) return scored
  return articles.slice(0, Math.min(2, articles.length))
}
