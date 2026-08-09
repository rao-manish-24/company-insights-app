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
    "masculine given name",
    "feminine given name",
    "common hindu",
    "god of the mind",
)


def description_is_rejected(description: str | None) -> bool:
    """True when the blurb is clearly a person/place/concept — not a company."""
    desc = (description or "").lower().strip()
    if not desc:
        return False
    return any(bit in desc for bit in _REJECT_DESCRIPTION_BITS)


def normalize_name(value: str) -> str:
    cleaned = _strip_accents(value or "")
    cleaned = _CORP_SUFFIXES.sub(" ", cleaned)
    cleaned = _NON_ALNUM.sub(" ", cleaned.lower()).strip()
    return " ".join(cleaned.split())


_VOWELS = frozenset("aeiouy")
_REPEATED_RUN_RE = re.compile(r"(.)\1{2,}")
# Squatted domains (hhhhhh.co, asdfgh.es) make Clearbit return keyboard mash as
# a "company", so reject the shape of the string before trusting any upstream.
_KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm", "qazwsxedcrfv")
_KEYBOARD_RUNS = frozenset(
    row[i : i + size]
    for source in _KEYBOARD_ROWS
    for row in (source, source[::-1])
    for size in (4, 5)
    for i in range(len(row) - size + 1)
)


def _token_is_gibberish(token: str) -> bool:
    t = token.lower()
    # Short tokens (3M, IBM, Q2) are legitimate and handled by other gates.
    if len(t) < 4 or not t.isalpha():
        return False
    # "hhhhhh" — three or more of the same letter in a row.
    if _REPEATED_RUN_RE.search(t):
        return True
    # "abab", "aabbaa" — almost no distinct letters.
    if len(set(t)) <= max(2, len(t) // 4):
        return True
    # "asdfgh", "qwerty" — keyboard mashing.
    if any(t[i : i + 4] in _KEYBOARD_RUNS for i in range(len(t) - 3)):
        return True
    # Long strings with no vowel at all ("HSBC"/"KPMG" are short, so safe).
    if len(t) >= 6 and not (set(t) & _VOWELS):
        return True
    return False


def looks_like_gibberish(value: str) -> bool:
    """True when every meaningful token is keyboard mash rather than a name."""
    tokens = [tok for tok in normalize_name(value).split() if len(tok) >= 4 and tok.isalpha()]
    if not tokens:
        return False
    return all(_token_is_gibberish(tok) for tok in tokens)


def stem_token(token: str) -> str:
    """Light plural stem so Device ≈ Devices (not a full NLP stemmer)."""
    t = (token or "").lower()
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith(("ss", "us", "is", "oes")):
        return t[:-1]
    return t


def stemmed_tokens(value: str) -> tuple[str, ...]:
    return tuple(stem_token(tok) for tok in normalize_name(value).split() if tok)


# Parent/operating-brand renames that market data often surfaces as the legal name.
_BRAND_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"google", "alphabet"}),
    frozenset({"facebook", "meta", "meta platforms"}),
    frozenset({"twitter", "x corp", "xai"}),
)

# When Yahoo returns the right ticker but a renamed legal entity (Google → Alphabet).
_QUERY_TICKERS: dict[str, frozenset[str]] = {
    "google": frozenset({"GOOGL", "GOOG"}),
    "alphabet": frozenset({"GOOGL", "GOOG"}),
    "facebook": frozenset({"META"}),
    "meta": frozenset({"META"}),
    "meta platforms": frozenset({"META"}),
    "apple": frozenset({"AAPL"}),
    "microsoft": frozenset({"MSFT"}),
    "tesla": frozenset({"TSLA"}),
    "amazon": frozenset({"AMZN"}),
    "nvidia": frozenset({"NVDA"}),
    "netflix": frozenset({"NFLX"}),
    "amd": frozenset({"AMD"}),
    "advanced micro devices": frozenset({"AMD"}),
    "advanced micro device": frozenset({"AMD"}),
    "siemens": frozenset({"SIEGY", "SIE.DE", "ENR.DE"}),
    "nestle": frozenset({"NSRGY", "NESN.SW"}),
    "nestlé": frozenset({"NSRGY", "NESN.SW"}),
}


def _brand_family(name: str) -> frozenset[str] | None:
    norm = normalize_name(name)
    if not norm:
        return None
    tokens = norm.split()
    core = tokens[0]
    for family in _BRAND_FAMILIES:
        if norm in family or core in family:
            return family
    return None


def same_brand_family(query: str, candidate: str | None) -> bool:
    left = _brand_family(query)
    right = _brand_family(candidate or "")
    return bool(left and right and left is right)


def names_align(query: str, candidate: str | None) -> bool:
    """Require real lexical overlap — not 'k' ⊆ 'kelvin' or 'apple' ⊆ 'apple hospitality'."""
    q = normalize_name(query)
    c = normalize_name(candidate or "")
    if not q or not c:
        return False

    # Short queries (1–2 chars): only exact normalized match (tickers like GM, BA, AI).
    if len(q) <= 2:
        return q == c or q == c.replace(" ", "")

    if q == c:
        return True

    # Near-plural phrases: "Advanced Micro Device" ≈ "Advanced Micro Devices"
    q_stem = stemmed_tokens(q)
    c_stem = stemmed_tokens(c)
    if q_stem and q_stem == c_stem:
        return True

    # Google ↔ Alphabet, Facebook ↔ Meta, etc.
    if same_brand_family(q, c):
        return True

    q_tokens = q.split()
    c_tokens = c.split()
    if not q_tokens or not c_tokens:
        return False

    # Single-token brands ("Apple", "Tesla"): match the brand core only.
    # Token-overlap used to accept "Apple Hospitality REIT" for query "Apple".
    if len(q_tokens) == 1:
        if stem_token(c_tokens[0]) != stem_token(q_tokens[0]):
            return False
        return len(c_tokens) == 1

    if q in c or c in q:
        # Avoid tiny substring hits inside much longer unrelated labels.
        shorter, longer = (q, c) if len(q) <= len(c) else (c, q)
        if len(shorter) >= 3 and (len(shorter) / max(len(longer), 1)) >= 0.45:
            return True

    stem_overlap = set(q_stem) & set(c_stem)
    # Prefer stem overlap for multi-word near misses.
    if stem_overlap and (len(stem_overlap) / max(len(q_stem), 1)) >= 0.8 and len(q_stem) >= 2:
        return True

    # "Applied Micro Devices" must not match "Advanced Micro Devices" on shared tails.
    if (
        len(q_tokens) >= 2
        and len(c_tokens) >= 2
        and stem_token(q_tokens[0]) != stem_token(c_tokens[0])
    ):
        return False

    q_set, c_set = set(q_tokens), set(c_tokens)
    overlap = q_set & c_set
    return len(overlap) >= 1 and (len(overlap) / len(q_set)) >= 0.6


def description_looks_like_company(description: str | None) -> bool:
    desc = (description or "").lower().strip()
    if not desc:
        return False
    if description_is_rejected(desc):
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
        "semiconductor",
        "semiconductors",
        "chipmaker",
        "processor",
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
    # Known brand → ticker even when Yahoo legal name is the parent (Google → Alphabet).
    known = _QUERY_TICKERS.get(normalize_name(query))
    if known and ticker in known:
        return True
    market_name = market.get("name")
    return names_align(query, str(market_name) if market_name else None)


def is_curated_company(company_name: str) -> bool:
    """Names on the hand-maintained rescue list are real by construction.

    Wikidata resolves some firms to their founder's person entry (Roland Berger,
    Kearney), so the curated list has to outrank a missing company record.
    """
    # Imported lazily: the lookup service imports this module at load time.
    from app.services.company_lookup_service import KNOWN_COMPANY_STEMS

    return stemmed_tokens(company_name) in KNOWN_COMPANY_STEMS


def company_evidence_ok(
    company_name: str,
    *,
    profile: dict[str, Any] | None,
    market: dict[str, Any] | None,
) -> bool:
    """True when Wikidata/Wikipedia or market data actually back this company."""
    cleaned = " ".join((company_name or "").strip().split())
    if is_curated_company(cleaned):
        return True
    matched = (profile or {}).get("matched_label") if isinstance(profile, dict) else None
    wiki_desc = (profile or {}).get("matched_description") if isinstance(profile, dict) else None
    matched_text = str(matched) if matched else ""
    desc_text = str(wiki_desc) if wiki_desc else ""

    wiki_ok = False
    if matched and names_align(cleaned, matched_text):
        if not description_is_rejected(desc_text) and (
            description_looks_like_company(desc_text) or profile_has_company_signal(profile)
        ):
            wiki_ok = True

    return wiki_ok or market_supports_company(cleaned, market)


def articles_mention_company(company_name: str, articles: Any) -> bool:
    """True when at least one article actually names this company."""
    tokens = [tok for tok in normalize_name(company_name).split() if tok]
    if not tokens:
        return False
    width = len(tokens)
    for article in articles or []:
        title = getattr(article, "title", None) or ""
        description = getattr(article, "description", None) or ""
        words = normalize_name(f"{title} {description}").split()
        # Whole-word run so "lily" does not match "family".
        if any(words[i : i + width] == tokens for i in range(len(words) - width + 1)):
            return True
    return False


def assert_valid_company(
    company_name: str,
    *,
    profile: dict[str, Any] | None,
    market: dict[str, Any] | None,
    identity_verified: bool = False,
    upstream_degraded: bool = False,
    articles: Any = None,
) -> None:
    cleaned = " ".join((company_name or "").strip().split())
    if len(cleaned) < 2:
        raise BadRequestError("Not a valid company name. Enter at least 2 characters.")

    if not re.search(r"[A-Za-z]", cleaned):
        raise BadRequestError("Not a valid company name. Use letters in the company name.")

    # Squatted domains make keyboard mash look like a company to autocomplete.
    if looks_like_gibberish(cleaned):
        raise BadRequestError(
            f"Not a valid company name: “{cleaned}”. "
            "Enter a real company (for example Microsoft, Nestlé, or Siemens)."
        )

    # Curated list outranks Wikidata, which maps some firms to their founder.
    if is_curated_company(cleaned):
        return

    matched = (profile or {}).get("matched_label") if isinstance(profile, dict) else None
    wiki_desc = (profile or {}).get("matched_description") if isinstance(profile, dict) else None
    matched_text = str(matched) if matched else ""
    desc_text = str(wiki_desc) if wiki_desc else ""

    # Positive non-company evidence (given name / person) always rejects.
    if matched and names_align(cleaned, matched_text) and description_is_rejected(desc_text):
        raise BadRequestError(
            f"Not a valid company name: “{cleaned}”. "
            "Enter a real company (for example Microsoft, Nestlé, or Siemens)."
        )

    if company_evidence_ok(cleaned, profile=profile, market=market):
        return

    # No registry record, so fall back to real news coverage naming the company.
    # This is what keeps genuine private firms working without a Wikidata entry.
    if articles_mention_company(cleaned, articles):
        return

    # Nothing at all. Only a registry-grade identity gets the benefit of the
    # doubt, and only when the upstreams that would have proven it were actually
    # throttled (403/429) rather than answering cleanly with "nothing exists".
    if identity_verified and upstream_degraded:
        return

    raise BadRequestError(
        f"Not a valid company name: “{cleaned}”. "
        "Enter a real company (for example Microsoft, Nestlé, or Siemens)."
    )
