"""Decide whether a query resolves to a real company before spending LLM tokens."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.core.exceptions import BadRequestError

_CORP_SUFFIXES = re.compile(
    r"\b(incorporated|inc\.?|corp\.?|corporation|ltd\.?|limited|llc|plc|co\.?|company|group|"
    r"holdings?|technologies|technology|systems|sa|ag|nv|gmbh|kk)\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))

# Wikidata / Yahoo often map single letters to units, currencies, or concepts.
_REJECT_DESCRIPTION_BITS = (
    "unit of",
    "si unit",
    "currency",
    "letter",
    "alphabet",
    "chemical element",
    "mathematical",
    "disambiguation",
    "wikimedia",
    "fictional",
    "given name",
    "family name",
    "surname",
    "first name",
    "personal name",
    "male name",
    "female name",
    "human settlement",
    "village",
    "film",
    "song",
    "album",
    "businessperson",
    "business person",
    "entrepreneur",
    "politician",
    "actor",
    "actress",
    "singer",
    "writer",
    "footballer",
    "cricketer",
    "child of",
    "human being",
)


def normalize_name(value: str) -> str:
    cleaned = _strip_accents(value or "")
    cleaned = _CORP_SUFFIXES.sub(" ", cleaned)
    cleaned = _NON_ALNUM.sub(" ", cleaned.lower()).strip()
    return " ".join(cleaned.split())


def names_align(query: str, candidate: str | None) -> bool:
    """Require real lexical overlap — not 'k' ⊆ 'kelvin'."""
    q = normalize_name(query)
    c = normalize_name(candidate or "")
    if not q or not c:
        return False

    # Short queries (1–2 chars): only exact normalized match (tickers like GM, BA, AI).
    if len(q) <= 2:
        return q == c or q == c.replace(" ", "")

    if q == c:
        return True
    if q in c or c in q:
        # Avoid tiny substring hits inside much longer unrelated labels.
        shorter, longer = (q, c) if len(q) <= len(c) else (c, q)
        if len(shorter) >= 3 and (len(shorter) / max(len(longer), 1)) >= 0.45:
            return True

    q_tokens = set(q.split())
    c_tokens = set(c.split())
    if not q_tokens or not c_tokens:
        return False
    overlap = q_tokens & c_tokens
    return len(overlap) >= 1 and (len(overlap) / len(q_tokens)) >= 0.6


def description_looks_like_company(description: str | None) -> bool:
    desc = (description or "").lower().strip()
    if not desc:
        return False
    if any(bit in desc for bit in _REJECT_DESCRIPTION_BITS):
        return False
    # Biographical blurbs ("born 1985") are people, not companies.
    if re.search(r"\bborn\b|\b\d{4}\s*[–-]\s*\d{0,4}\b", desc):
        return False
    preferred = (
        "company",
        "corporation",
        "enterprise",
        "manufacturer",
        "technology company",
        "software",
        "bank",
        "group of companies",
        "multinational",
        "holding company",
        "startup",
        "retailer",
        "airline",
        "automotive",
        "telecommunications",
        "consulting",
        "firm",
        "apparel",
        "fashion",
        "boutique",
        "restaurant",
        "food",
        "solar",
        "energy",
        "design",
        "brand",
        "gmbh",
        "brokerage",
        "broker",
        "real estate",
        "marketplace",
        "platform",
        "organization",
        "organisation",
        "provider",
        "publisher",
        "agency",
        "artificial intelligence",
        "subsidiary",
        "aerospace",
        "social media",
        "chatbot",
    )
    if any(bit in desc for bit in preferred):
        return True
    # Require word-boundary "business" so "businessperson" does not qualify.
    return bool(re.search(r"\bbusiness\b", desc))


def profile_has_company_signal(profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    if profile.get("founded") or profile.get("headquarters") or profile.get("employees"):
        return True
    if profile.get("revenue") or profile.get("parent_company"):
        return True
    people = profile.get("key_people") or []
    for person in people:
        if isinstance(person, dict) and person.get("name"):
            return True
    return False


def market_supports_company(query: str, market: dict[str, Any] | None) -> bool:
    if not isinstance(market, dict) or not market.get("ticker"):
        return False
    ticker = str(market.get("ticker") or "").strip().upper()
    q_compact = re.sub(r"[^A-Z0-9.\-]", "", query.strip().upper())
    # Direct ticker entry (MSFT, BRK.B)
    if q_compact and q_compact == ticker.replace(" ", ""):
        return True
    market_name = market.get("name")
    return names_align(query, str(market_name) if market_name else None)


def assert_valid_company(
    company_name: str,
    *,
    profile: dict[str, Any] | None,
    market: dict[str, Any] | None,
) -> None:
    cleaned = " ".join((company_name or "").strip().split())
    if len(cleaned) < 2:
        raise BadRequestError("Not a valid company name. Enter at least 2 characters.")

    if not re.search(r"[A-Za-z]", cleaned):
        raise BadRequestError("Not a valid company name. Use letters in the company name.")

    wiki_ok = False
    matched = (profile or {}).get("matched_label") if isinstance(profile, dict) else None
    wiki_desc = (profile or {}).get("matched_description") if isinstance(profile, dict) else None
    if matched and names_align(cleaned, str(matched)):
        if description_looks_like_company(str(wiki_desc) if wiki_desc else None) or profile_has_company_signal(
            profile
        ):
            wiki_ok = True

    market_ok = market_supports_company(cleaned, market)

    if wiki_ok or market_ok:
        return

    raise BadRequestError(
        f"Not a valid company name: “{cleaned}”. "
        "Enter a real company (for example Microsoft, Nestlé, or Siemens)."
    )
