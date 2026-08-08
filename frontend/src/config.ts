const raw = import.meta.env.VITE_API_BASE_URL?.trim()

export const API_BASE =
  raw && raw.length > 0
    ? raw.replace(/\/$/, '')
    : import.meta.env.PROD
      ? '/api'
      : 'http://localhost:8000/api'

export const REQUEST_TIMEOUT_MS = 120_000
