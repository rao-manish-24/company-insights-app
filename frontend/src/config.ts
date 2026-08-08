const raw = import.meta.env.VITE_API_BASE_URL?.trim()

// Dev: use Vite proxy (/api → backend) so localhost vs 127.0.0.1 never breaks CORS.
export const API_BASE =
  raw && raw.length > 0
    ? raw.replace(/\/$/, '')
    : '/api'

export const REQUEST_TIMEOUT_MS = 120_000
