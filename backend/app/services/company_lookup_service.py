"""Resolve company queries with confidence scores and suggestions."""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.http import get_fast_http_client, get_http_client, get_json
from app.core.rate_limit import lookup_cache
from app.services.company_validation import (
    description_is_rejected,
    description_looks_like_company,
    normalize_name,
    stemmed_tokens,
)
from app.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
CLEARBIT_SUGGEST_API = "https://autocomplete.clearbit.com/v1/companies/suggest"

ResolveStatus = Literal["exact", "ambiguous", "not_found"]
MatchKind = Literal[
    "exact",
    "ticker",
    "brand_suffix",
    "prefix_words",
    "prefix_compact",
    "token",
    "contains",
    "none",
]

# Auto-analyze only when the name is a clear, high-confidence company match.
EXACT_CONFIDENCE = 0.92
# Show as "did you mean" / starts-with suggestions (stricter than before).
SUGGEST_CONFIDENCE = 0.55
# Live autocomplete while typing — Clearbit-only, still fairly strict.
AUTOCOMPLETE_CONFIDENCE = 0.60
# Minimum gap between #1 exact and next rival before auto-analyze on fuzzy ties.
EXACT_GAP = 0.10
_STRONG_SUGGEST_KINDS = frozenset({"exact", "ticker", "brand_suffix", "prefix_words", "prefix_compact"})

_PLACEHOLDER_QUERIES = frozenset(
    {"xyz", "abc", "asdf", "qwerty", "foo", "bar", "baz", "xxx", "zzz", "test", "testing"}
)
_ADULT_OR_SPAM_DOMAIN_BITS = (
    "redtube",
    "pornhub",
    "xvideos",
    "xnxx",
    "onlyfans",
    "redgifs",
)
# Keep probe set small — only used when the primary Clearbit search is thin.
_SHORT_QUERY_PROBES = ("hat", "bull", "energy", "lily", "taco", "sparrow")
_CORP_SUFFIX_TOKENS = frozenset(
    {
        "s",
        "a",
        "sa",
        "inc",
        "ltd",
        "llc",
        "plc",
        "co",
        "corp",
        "corporation",
        "company",
        "group",
        "ag",
        "nv",
        "gmbh",
        "holdings",
        "holding",
        "limited",
    }
)
_SOURCE_RANK = {"wikidata": 0, "wikipedia": 1, "yahoo": 2, "clearbit": 3}

# Canonical rescue when upstream search is thin (Render IP blocks / empty Clearbit).
# Keys are stemmed token tuples from company_validation.stemmed_tokens().
# Values: (canonical name, ticker or "", optional blurb for private firms).
_KNOWN_STEM_COMPANIES: dict[tuple[str, ...], tuple[str, str] | tuple[str, str, str]] = {
    ("advanced", "micro", "device"): ("Advanced Micro Devices, Inc.", "AMD"),
    ("apple",): ("Apple Inc.", "AAPL"),
    ("microsoft",): ("Microsoft Corporation", "MSFT"),
    ("tesla",): ("Tesla, Inc.", "TSLA"),
    ("nvidia",): ("NVIDIA Corporation", "NVDA"),
    ("amazon",): ("Amazon.com, Inc.", "AMZN"),
    ("alphabet",): ("Alphabet Inc.", "GOOGL"),
    ("google",): ("Alphabet Inc.", "GOOGL"),
    ("meta",): ("Meta Platforms, Inc.", "META"),
    ("facebook",): ("Meta Platforms, Inc.", "META"),
    ("netflix",): ("Netflix, Inc.", "NFLX"),
    ("intel",): ("Intel Corporation", "INTC"),
    ("ibm",): ("International Business Machines Corporation", "IBM"),
    ("oracle",): ("Oracle Corporation", "ORCL"),
    ("salesforce",): ("Salesforce, Inc.", "CRM"),
    ("adobe",): ("Adobe Inc.", "ADBE"),
    ("uber",): ("Uber Technologies, Inc.", "UBER"),
    ("airbnb",): ("Airbnb, Inc.", "ABNB"),
    ("spotify",): ("Spotify Technology S.A.", "SPOT"),
    ("paypal",): ("PayPal Holdings, Inc.", "PYPL"),
    ("visa",): ("Visa Inc.", "V"),
    ("mastercard",): ("Mastercard Incorporated", "MA"),
    ("jpmorgan",): ("JPMorgan Chase & Co.", "JPM"),
    ("jp", "morgan"): ("JPMorgan Chase & Co.", "JPM"),
    ("goldman",): ("The Goldman Sachs Group, Inc.", "GS"),
    ("goldman", "sach"): ("The Goldman Sachs Group, Inc.", "GS"),
    ("morgan", "stanley"): ("Morgan Stanley", "MS"),
    ("accenture",): ("Accenture plc", "ACN"),
    ("deloitte",): ("Deloitte", "", "Professional services firm"),
    ("mckinsey",): ("McKinsey & Company", "", "Management consulting firm"),
    ("bcg",): ("Boston Consulting Group", "", "Management consulting firm"),
    ("boston", "consulting"): ("Boston Consulting Group", "", "Management consulting firm"),
    # Keys must use stemmed_tokens() form (siemens → siemen).
    ("siemen",): ("Siemens AG", "SIEGY"),
    ("nestle",): ("Nestlé S.A.", "NSRGY"),
    ("bain",): ("Bain & Company", "", "Management consulting firm"),
    ("spacex",): ("SpaceX", "", "Aerospace manufacturer and spaceflight company"),
    ("openai",): ("OpenAI", "", "Artificial intelligence research company"),
}


@dataclass(frozen=True)
class _QueryParts:
    raw: str
    norm: str
    compact: str
    tokens: tuple[str, ...]
    is_ticker: bool


@dataclass
class CompanySuggestion:
    name: str
    description: str | None
    confidence: float
    source: str
    ticker: str | None = None
    location: str | None = None
    match_kind: MatchKind = "none"


@dataclass
class CompanyResolution:
    query: str
    status: ResolveStatus
    confidence: float
    matched_name: str | None
    message: str
    suggestions: list[CompanySuggestion]


class CompanyLookupService:
    def __init__(self, market_service: MarketDataService | None = None) -> None:
        self.market_service = market_service or MarketDataService()
        # Shared pooled clients (Wikimedia-compliant UA + circuit breaker).
        self._client = get_http_client()
        self._suggest_client = get_fast_http_client()

    def close(self) -> None:
        """No-op: HTTP clients are shared process-wide."""

    def suggest(self, query: str, *, limit: int = 6) -> list[CompanySuggestion]:
        """Fast autocomplete: known + Clearbit first; Yahoo/Wiki only if still empty."""
        cleaned = " ".join((query or "").strip().split())
        if len(cleaned) < 2 or not re.search(r"[A-Za-z]", cleaned):
            return []
        parts = self._query_parts(cleaned)
        if parts.norm in _PLACEHOLDER_QUERIES:
            return []

        out: list[CompanySuggestion] = []
        seen_domains: set[str] = set()

        # Instant local hits before any network (Bain, Siemens, mega-caps).
        out.extend(self._known_company_fallbacks(parts))

        for term in self._near_query_variants(cleaned)[:2]:
            try:
                rows = self._fetch_clearbit(term, client=self._suggest_client)
                self._ingest_clearbit_rows(parts, rows, out=out, seen_domains=seen_domains)
            except Exception:
                logger.warning(
                    "Autocomplete suggest failed query=%r term=%r", cleaned, term, exc_info=True
                )

        strong = [item for item in out if item.confidence >= AUTOCOMPLETE_CONFIDENCE]
        # Avoid Yahoo/Wiki while typing unless Clearbit is empty — they burn rate limits.
        if len(strong) < 1 and len(parts.compact) >= 4:
            try:
                out.extend(self._yahoo_candidates(parts))
            except Exception:
                logger.warning("Autocomplete yahoo fallback failed query=%r", cleaned, exc_info=True)

        strong = [item for item in out if item.confidence >= AUTOCOMPLETE_CONFIDENCE]
        if len(strong) < 1 and len(parts.compact) >= 5:
            try:
                out.extend(self._wikipedia_candidates(parts))
            except Exception:
                logger.warning(
                    "Autocomplete wikipedia fallback failed query=%r", cleaned, exc_info=True
                )

        # Short-prefix Clearbit probes only when still thin (Red Hat / Pink Lily).
        strong = [item for item in out if item.confidence >= AUTOCOMPLETE_CONFIDENCE]
        if " " not in cleaned and 4 <= len(cleaned) <= 6 and len(strong) < 2:
            probe_terms = [f"{cleaned} {suffix}" for suffix in _SHORT_QUERY_PROBES[:2]]

            def _probe(term: str) -> list[Any]:
                try:
                    return self._fetch_clearbit(term, client=self._suggest_client)
                except Exception:
                    return []

            with ThreadPoolExecutor(max_workers=2) as pool:
                for rows in pool.map(_probe, probe_terms):
                    if rows:
                        self._ingest_clearbit_rows(
                            parts, rows, out=out, seen_domains=seen_domains
                        )

        ranked = sorted(
            out,
            key=lambda item: (
                item.confidence,
                -_SOURCE_RANK.get(item.source, 9),
                self._listing_rank(item),
            ),
            reverse=True,
        )
        suggestions: list[CompanySuggestion] = []
        seen_names: set[str] = set()
        for item in ranked:
            if item.confidence < AUTOCOMPLETE_CONFIDENCE:
                continue
            if item.match_kind not in _STRONG_SUGGEST_KINDS:
                continue
            if not self._is_company_grade(item):
                continue
            key = normalize_name(item.name)
            if not key or key in seen_names:
                continue
            seen_names.add(key)
            suggestions.append(item)
            if len(suggestions) >= limit:
                break
        return suggestions

    def quick_verify(self, company_name: str) -> tuple[str, str | None] | None:
        """Cheap identity check for analyze after client resolve — no Wiki/Yahoo burst.

        Returns (matched_name, ticker) when known stems or Clearbit prove company-grade.
        """
        cleaned = " ".join((company_name or "").strip().split())
        if len(cleaned) < 2:
            return None
        cache_key = f"quick:{cleaned.lower()}"
        cached = lookup_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("name"):
            return str(cached["name"]), cached.get("ticker")

        parts = self._query_parts(cleaned)
        candidates = self._known_company_fallbacks(parts)
        try:
            clearbit = self._clearbit_candidates(parts)
            candidates.extend(clearbit)
        except Exception:
            logger.warning("quick_verify clearbit failed company=%r", cleaned, exc_info=True)

        company_grade = [item for item in candidates if self._is_company_grade(item)]
        exact_hits = [
            item
            for item in company_grade
            if self._is_exact_match(parts, item) and item.confidence >= EXACT_CONFIDENCE
        ]
        if not exact_hits:
            return None
        chosen = exact_hits[0]
        if description_is_rejected(chosen.description):
            return None
        raw_tokens = tuple(re.findall(r"[a-z0-9]+", cleaned.lower()))
        label_tokens = tuple(re.findall(r"[a-z0-9]+", chosen.name.lower()))
        accepted = (
            self._should_auto_analyze(parts, chosen, company_grade)
            or raw_tokens == label_tokens
            or normalize_name(chosen.name) == parts.norm
        )
        if not accepted:
            return None
        lookup_cache.set(
            cache_key,
            {"name": chosen.name, "ticker": chosen.ticker},
            ttl_seconds=600,
            stale_seconds=1800,
        )
        return chosen.name, chosen.ticker

    def resolve(self, query: str, *, limit: int = 8) -> CompanyResolution:
        cleaned = " ".join((query or "").strip().split())
        if len(cleaned) < 2 or not re.search(r"[A-Za-z]", cleaned):
            return CompanyResolution(
                query=cleaned,
                status="not_found",
                confidence=0.0,
                matched_name=None,
                message="No valid companies found with this name.",
                suggestions=[],
            )
        parts = self._query_parts(cleaned)
        if parts.norm in _PLACEHOLDER_QUERIES:
            return CompanyResolution(
                query=cleaned,
                status="not_found",
                confidence=0.0,
                matched_name=None,
                message=f'No valid companies found with this name: “{cleaned}”.',
                suggestions=[],
            )

        cache_key = f"resolve:{cleaned.lower()}"
        cached = lookup_cache.get(cache_key)
        if isinstance(cached, dict):
            restored = self._resolution_from_cache(cached)
            if restored is not None:
                logger.info("Resolve cache hit query=%r status=%s", cleaned, restored.status)
                return restored

        # Fast path: known stems + Clearbit only — skip Wiki/Yahoo when already exact.
        fast: list[CompanySuggestion] = list(self._known_company_fallbacks(parts))
        try:
            fast.extend(self._clearbit_candidates(parts))
        except Exception:
            logger.warning("Resolve clearbit fast-path failed query=%r", cleaned, exc_info=True)
        resolution = self._decide_resolution(cleaned, parts, fast, limit=limit)
        if resolution.status == "exact":
            self._cache_resolution(cache_key, resolution)
            return resolution

        # Full path for ambiguous / thin Clearbit (Wikipedia recovers SpaceXAI, etc.).
        candidates = self._collect_candidates(parts) + self._known_company_fallbacks(parts)
        resolution = self._decide_resolution(cleaned, parts, candidates, limit=limit)
        self._cache_resolution(cache_key, resolution)
        return resolution

    def _decide_resolution(
        self,
        cleaned: str,
        parts: _QueryParts,
        candidates: list[CompanySuggestion],
        *,
        limit: int,
    ) -> CompanyResolution:
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.confidence,
                -_SOURCE_RANK.get(item.source, 9),
                self._listing_rank(item),
                -len(item.name),
            ),
            reverse=True,
        )
        deduped: list[CompanySuggestion] = []
        seen: set[str] = set()
        for item in ranked:
            key = normalize_name(item.name)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)

        if not deduped:
            return CompanyResolution(
                query=cleaned,
                status="not_found",
                confidence=0.0,
                matched_name=None,
                message=f'No valid companies found with this name: “{cleaned}”.',
                suggestions=[],
            )

        company_grade = [item for item in deduped if self._is_company_grade(item)]
        exact_hits = [
            item
            for item in company_grade
            if self._is_exact_match(parts, item) and item.confidence >= EXACT_CONFIDENCE
        ]
        if exact_hits and self._should_auto_analyze(parts, exact_hits[0], company_grade):
            chosen = exact_hits[0]
            return CompanyResolution(
                query=cleaned,
                status="exact",
                confidence=chosen.confidence,
                matched_name=chosen.name,
                message=f"Matched “{chosen.name}” (confidence {chosen.confidence:.0%}).",
                suggestions=company_grade[:limit],
            )

        suggestable = [
            item
            for item in company_grade
            if item.confidence >= SUGGEST_CONFIDENCE and self._is_useful_suggestion(parts, item)
        ]
        if suggestable:
            return CompanyResolution(
                query=cleaned,
                status="ambiguous",
                confidence=suggestable[0].confidence,
                matched_name=None,
                message=(
                    f'Company name “{cleaned}” does not exist as an exact match. '
                    "Did you mean one of these?"
                ),
                suggestions=suggestable[:limit],
            )

        return CompanyResolution(
            query=cleaned,
            status="not_found",
            confidence=0.0,
            matched_name=None,
            message=f'No valid companies found with this name: “{cleaned}”.',
            suggestions=[],
        )

    def _cache_resolution(self, cache_key: str, resolution: CompanyResolution) -> None:
        lookup_cache.set(
            cache_key,
            self.to_dict(resolution),
            ttl_seconds=180,
            stale_seconds=600,
        )

    def _resolution_from_cache(self, payload: dict[str, Any]) -> CompanyResolution | None:
        try:
            suggestions = [
                CompanySuggestion(
                    name=str(item.get("name") or ""),
                    description=item.get("description"),
                    confidence=float(item.get("confidence") or 0),
                    source=str(item.get("source") or "cache"),
                    ticker=item.get("ticker"),
                    location=item.get("location"),
                    match_kind=item.get("match_kind") or "none",
                )
                for item in (payload.get("suggestions") or [])
                if isinstance(item, dict) and item.get("name")
            ]
            status = payload.get("status") or "not_found"
            if status not in {"exact", "ambiguous", "not_found"}:
                return None
            return CompanyResolution(
                query=str(payload.get("query") or ""),
                status=status,
                confidence=float(payload.get("confidence") or 0),
                matched_name=payload.get("matched_name"),
                message=str(payload.get("message") or ""),
                suggestions=suggestions,
            )
        except Exception:
            logger.warning("Corrupt resolve cache payload", exc_info=True)
            return None

    def _query_parts(self, query: str) -> _QueryParts:
        norm = normalize_name(query)
        return _QueryParts(
            raw=query,
            norm=norm,
            compact=re.sub(r"[^a-z0-9]", "", norm),
            tokens=tuple(norm.split()) if norm else (),
            is_ticker=bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,5}", query.strip())),
        )

    def _collect_candidates(self, parts: _QueryParts) -> list[CompanySuggestion]:
        # Parallelize independent upstream lookups (incl. Wikipedia for new brand names).
        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_wiki = pool.submit(self._wikidata_candidates, parts)
            fut_wikipedia = pool.submit(self._wikipedia_candidates, parts)
            fut_yahoo = pool.submit(self._yahoo_candidates, parts)
            fut_clear = pool.submit(self._clearbit_candidates, parts)
            wiki = fut_wiki.result()
            wikipedia = fut_wikipedia.result()
            yahoo = fut_yahoo.result()
            clearbit = fut_clear.result()
        return wiki + wikipedia + yahoo + clearbit

    def _near_query_variants(self, query: str) -> list[str]:
        """Plural/singular last-token variants (Device ↔ Devices)."""
        cleaned = " ".join((query or "").strip().split())
        if not cleaned:
            return []
        variants = [cleaned]
        tokens = cleaned.split()
        if len(tokens) >= 2:
            last = tokens[-1]
            low = last.lower()
            if len(low) > 3 and low.endswith("s") and not low.endswith(("ss", "us", "is", "oes")):
                variants.append(" ".join(tokens[:-1] + [last[:-1]]))
            elif len(low) > 2 and not low.endswith("s"):
                variants.append(" ".join(tokens[:-1] + [last + "s"]))
        seen: set[str] = set()
        ordered: list[str] = []
        for term in variants:
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(term)
        return ordered

    def _known_company_fallbacks(self, parts: _QueryParts) -> list[CompanySuggestion]:
        """Inject mega-cap matches when live search returns nothing useful."""
        stem = stemmed_tokens(parts.norm)
        hit = _KNOWN_STEM_COMPANIES.get(stem)
        if not hit:
            return []
        name = hit[0]
        ticker = hit[1]
        private_blurb = hit[2] if len(hit) > 2 else "Private company"
        if ticker:
            description = f"Public company · {ticker}"
            source = "yahoo"
            location = "NMS"
        else:
            description = private_blurb
            source = "wikipedia"
            location = None
        scored = self._score_parts(
            parts,
            name,
            description,
            source=source,
            ticker=ticker or None,
        )
        if scored["confidence"] < SUGGEST_CONFIDENCE:
            return []
        return [
            CompanySuggestion(
                name=name,
                description=description,
                confidence=max(scored["confidence"], 0.93),
                source=source,
                ticker=ticker or None,
                location=location,
                match_kind=scored["match_kind"],
            )
        ]

    def _clearbit_search_terms(self, query: str) -> list[str]:
        terms = list(self._near_query_variants(query))
        q = query.strip()
        if " " not in q and 3 <= len(q) <= 8:
            terms.extend(f"{q} {suffix}" for suffix in _SHORT_QUERY_PROBES)
        seen: set[str] = set()
        ordered: list[str] = []
        for term in terms:
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(term)
        return ordered

    def _ingest_clearbit_rows(
        self,
        parts: _QueryParts,
        rows: list[Any],
        *,
        out: list[CompanySuggestion],
        seen_domains: set[str],
    ) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = (row.get("name") or "").strip()
            domain = (row.get("domain") or "").strip().lower()
            if not name:
                continue
            if domain and domain in seen_domains:
                continue
            if domain and any(bit in domain for bit in _ADULT_OR_SPAM_DOMAIN_BITS):
                continue
            if self._looks_like_person_name(name, parts.norm, domain=domain):
                continue
            if not self._strong_name_relation(parts, name) and not self._domain_supports_query(
                parts, domain
            ):
                continue
            if domain:
                seen_domains.add(domain)

            host_compact = re.sub(r"[^a-z0-9]", "", (domain or "").split(".")[0].lower())
            exact_domain = (
                bool(parts.compact)
                and host_compact == parts.compact
                and len(parts.compact) >= 5
            )
            if exact_domain and parts.norm != normalize_name(name):
                name = parts.raw.strip()

            desc = f"Company · {domain}" if domain else "Company"
            scored = self._score_parts(
                parts,
                name,
                desc,
                source="clearbit",
                domain=domain,
                exact_domain=exact_domain,
            )
            if scored["confidence"] < 0.25:
                continue
            out.append(
                CompanySuggestion(
                    name=name,
                    description=desc,
                    confidence=scored["confidence"],
                    source="clearbit",
                    location=domain or None,
                    match_kind=scored["match_kind"],
                )
            )

    def _fetch_clearbit(self, term: str, *, client: httpx.Client | None = None) -> list[Any]:
        cache_key = f"clearbit:{term.lower()}"
        cached = lookup_cache.get(cache_key)
        if isinstance(cached, list):
            return cached
        http = client or self._suggest_client
        try:
            response = http.get(
                CLEARBIT_SUGGEST_API,
                params={"query": term},
                headers={"Accept": "application/json"},
            )
            if response.status_code in {403, 429} or response.status_code >= 500:
                logger.warning(
                    "Clearbit soft-fail status=%s term=%r", response.status_code, term
                )
                return []
            response.raise_for_status()
            rows = response.json()
            payload = rows if isinstance(rows, list) else []
        except Exception:
            logger.warning("Clearbit request failed term=%r", term, exc_info=True)
            return []
        lookup_cache.set(cache_key, payload, ttl_seconds=300, stale_seconds=900)
        return payload

    def _clearbit_candidates(self, parts: _QueryParts) -> list[CompanySuggestion]:
        out: list[CompanySuggestion] = []
        seen_domains: set[str] = set()
        terms = self._clearbit_search_terms(parts.raw)
        primary = terms[0]
        probe_terms = terms[1:]
        try:
            self._ingest_clearbit_rows(
                parts, self._fetch_clearbit(primary), out=out, seen_domains=seen_domains
            )
        except Exception:
            logger.warning(
                "Clearbit company suggest failed query=%r term=%r", parts.raw, primary, exc_info=True
            )

        # Only probe when primary results are thin — caps network cost.
        useful = [
            item
            for item in out
            if item.confidence >= SUGGEST_CONFIDENCE
            and (
                item.match_kind in {"prefix_words", "exact", "brand_suffix"}
                or " " in item.name
            )
        ]
        if probe_terms and len(useful) < 3:
            for term in probe_terms[:3]:
                try:
                    self._ingest_clearbit_rows(
                        parts, self._fetch_clearbit(term), out=out, seen_domains=seen_domains
                    )
                except Exception:
                    logger.warning(
                        "Clearbit company suggest failed query=%r term=%r",
                        parts.raw,
                        term,
                        exc_info=True,
                    )
                useful = [
                    item
                    for item in out
                    if item.confidence >= SUGGEST_CONFIDENCE
                    and (
                        item.match_kind in {"prefix_words", "exact", "brand_suffix"}
                        or " " in item.name
                    )
                ]
                if len(useful) >= 4:
                    break
        return out

    def _domain_supports_query(self, parts: _QueryParts, domain: str | None) -> bool:
        if not domain or not parts.compact:
            return False
        host_compact = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
        return host_compact.startswith(parts.compact) or parts.compact in host_compact

    def _looks_like_person_name(self, name: str, query_norm: str, domain: str | None = None) -> bool:
        """Reject Clearbit hits like 'Manish Malhotra' while keeping 'Pink Lily'."""
        tokens = [tok for tok in re.split(r"\s+", name.strip()) if tok]
        if len(tokens) < 2 or not query_norm:
            return False
        if normalize_name(tokens[0]) != query_norm:
            return False

        lowered = name.lower()
        if re.search(r"&\s*co\.?\b|\band\s+co\.?\b", lowered):
            return True

        brand_second_words = {
            "lily",
            "taco",
            "energy",
            "sparrow",
            "hat",
            "bull",
            "group",
            "care",
            "tech",
            "decor",
            "jobs",
            "bike",
            "cherry",
            "villa",
            "bubble",
            "fin",
            "wire",
            "cat",
            "violet",
            "technologies",
            "technology",
            "systems",
            "soft",
            "software",
            "media",
            "labs",
            "lab",
            "studio",
            "studios",
            "digital",
            "capital",
            "partners",
            "ventures",
            "health",
            "foods",
            "fashion",
            "apparel",
        }
        second = normalize_name(tokens[1])
        if second in brand_second_words or any(tok.lower() in brand_second_words for tok in tokens[1:]):
            return False

        corp_bits = (
            "inc",
            "ltd",
            "llc",
            "corp",
            "company",
            "group",
            "technologies",
            "tech",
            "solutions",
            "services",
            "holdings",
            "limited",
            "plc",
        )
        if any(bit in lowered for bit in corp_bits):
            return False

        if 2 <= len(tokens) <= 3 and all(re.fullmatch(r"[A-Za-z][A-Za-z'.\-]*", tok) for tok in tokens):
            if domain:
                host = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
                last = re.sub(r"[^a-z0-9]", "", tokens[1].lower())
                if last and last in host and any(
                    marker in domain for marker in ("official", "blog", "portfolio", ".in")
                ):
                    return True
            if len(second) >= 4:
                return True
        return False

    def _wikipedia_candidates(self, parts: _QueryParts) -> list[CompanySuggestion]:
        """English Wikipedia search — catches new brand names Clearbit/Yahoo miss (e.g. SpaceXAI)."""
        hits: list[dict[str, Any]] = []
        seen_page_ids: set[int] = set()
        for term in self._near_query_variants(parts.raw):
            payload = get_json(
                WIKIPEDIA_API,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": term,
                    "srlimit": 8,
                    "format": "json",
                },
                client=self._client,
                label="wikipedia lookup",
            )
            if not payload:
                continue
            for hit in ((payload.get("query") or {}).get("search")) or []:
                if not isinstance(hit, dict):
                    continue
                page_id = hit.get("pageid")
                if isinstance(page_id, int):
                    if page_id in seen_page_ids:
                        continue
                    seen_page_ids.add(page_id)
                hits.append(hit)

        out: list[CompanySuggestion] = []
        seen: set[str] = set()
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            # Snippets are HTML-ish; strip tags for company-signal checks.
            snippet = re.sub(r"<[^>]+>", " ", hit.get("snippet") or "")
            snippet = re.sub(r"\s+", " ", snippet).strip() or None
            if not self._strong_name_relation(parts, title):
                continue
            # Never promote person/place pages (e.g. given-name "Manish") even on exact title match.
            if description_is_rejected(snippet):
                continue
            # Exact title matches (SpaceXAI) can pass with thin snippets; fuzzy needs company signal.
            if not description_looks_like_company(snippet) and normalize_name(title) != parts.norm:
                continue
            scored = self._score_parts(parts, title, snippet, source="wikipedia")
            if scored["confidence"] < 0.25:
                continue
            key = normalize_name(title)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(
                CompanySuggestion(
                    name=title,
                    description=snippet,
                    confidence=scored["confidence"],
                    source="wikipedia",
                    location="en.wikipedia.org",
                    match_kind=scored["match_kind"],
                )
            )
        return out

    def _wikidata_candidates(self, parts: _QueryParts) -> list[CompanySuggestion]:
        searches = list(self._near_query_variants(parts.raw))
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _pull(term: str) -> None:
            nonlocal results
            payload = get_json(
                WIKIDATA_API,
                params={
                    "action": "wbsearchentities",
                    "search": term,
                    "language": "en",
                    "type": "item",
                    "limit": 8,
                    "format": "json",
                },
                client=self._client,
                label="wikidata lookup",
            )
            if not payload:
                return
            for item in payload.get("search") or []:
                qid = str(item.get("id") or "")
                if qid and qid in seen_ids:
                    continue
                if qid:
                    seen_ids.add(qid)
                results.append(item)

        for term in searches[:2]:
            try:
                _pull(term)
            except Exception:
                logger.warning(
                    "Wikidata company lookup failed query=%r term=%r", parts.raw, term, exc_info=True
                )

        # Second search only if the first pass lacked company-grade labels.
        company_hits = 0
        for item in results:
            desc = (item.get("description") or "").strip() or None
            if description_looks_like_company(desc):
                company_hits += 1
        if company_hits < 2 and len(parts.raw) >= 3:
            try:
                _pull(f"{parts.raw} company")
            except Exception:
                logger.warning(
                    "Wikidata company lookup failed query=%r term=%r",
                    parts.raw,
                    f"{parts.raw} company",
                    exc_info=True,
                )

        out: list[CompanySuggestion] = []
        for item in results:
            label = (item.get("label") or "").strip()
            desc = (item.get("description") or "").strip() or None
            if not label or not description_looks_like_company(desc):
                continue
            if not self._strong_name_relation(parts, label):
                continue
            scored = self._score_parts(parts, label, desc, source="wikidata")
            if scored["confidence"] < 0.25:
                continue
            out.append(
                CompanySuggestion(
                    name=label,
                    description=desc,
                    confidence=scored["confidence"],
                    source="wikidata",
                    match_kind=scored["match_kind"],
                )
            )
        return out

    def _yahoo_candidates(self, parts: _QueryParts) -> list[CompanySuggestion]:
        quotes: list[dict[str, Any]] = []
        seen_symbols: set[str] = set()
        for term in self._near_query_variants(parts.raw):
            try:
                batch = self.market_service._search_quotes(term)  # noqa: SLF001
            except Exception:
                logger.exception("Yahoo company lookup failed query=%r term=%r", parts.raw, term)
                continue
            for quote in batch:
                symbol = str(quote.get("symbol") or "").upper()
                if not symbol or symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
                quotes.append(quote)

        out: list[CompanySuggestion] = []
        for quote in quotes:
            quote_type = (quote.get("quoteType") or "").upper()
            if quote_type and quote_type != "EQUITY":
                continue
            name = (quote.get("longname") or quote.get("shortname") or "").strip()
            symbol = str(quote.get("symbol") or "").strip() or None
            if not name and symbol:
                name = symbol
            if not name:
                continue
            if re.search(r"\b(etf|etn|fund|trust|cdr|depositary)\b", name, re.I):
                continue
            exchange = quote.get("exchDisp") or quote.get("exchange")
            industry = quote.get("industry") or quote.get("sector")
            desc_bits = [bit for bit in (industry, exchange) if bit]
            desc = " · ".join(str(bit) for bit in desc_bits) or None
            scored = self._score_parts(parts, name, desc, source="yahoo", ticker=symbol)
            if scored["confidence"] < 0.25:
                continue
            out.append(
                CompanySuggestion(
                    name=name,
                    description=desc,
                    confidence=scored["confidence"],
                    source="yahoo",
                    ticker=symbol,
                    location=str(exchange) if exchange else None,
                    match_kind=scored["match_kind"],
                )
            )
        return out

    def _classify_match(self, parts: _QueryParts, label: str, ticker: str | None = None) -> MatchKind:
        c = normalize_name(label)
        if not parts.norm or not c:
            return "none"
        c_compact = re.sub(r"[^a-z0-9]", "", c)
        ticker_norm = re.sub(r"[^a-z0-9.\-]", "", (ticker or "").lower())

        # "Q2 Holdings, Inc." normalizes to "q2" — treat as brand+suffix, not a bare exact echo.
        if self._is_query_plus_corp_suffix(parts, label):
            return "brand_suffix"
        if parts.norm == c or parts.compact == c_compact:
            return "exact"
        # "Advanced Micro Device" ≈ "Advanced Micro Devices"
        if stemmed_tokens(parts.norm) and stemmed_tokens(parts.norm) == stemmed_tokens(c):
            return "exact"
        if self._is_brand_with_corp_noise(parts.norm, c):
            return "brand_suffix"
        if (
            parts.is_ticker
            and ticker_norm
            and parts.compact == ticker_norm.replace(".", "").replace("-", "")
        ):
            return "ticker"
        first = c.split()[0]
        if c.startswith(parts.norm + " ") or (first == parts.norm and len(c.split()) > 1):
            return "prefix_words"
        # Compact prefix on the first token only (avoids manish⊂manishagarg).
        first_compact = re.sub(r"[^a-z0-9]", "", first)
        if first_compact.startswith(parts.compact) and len(first_compact) > len(parts.compact):
            rest = first_compact[len(parts.compact) :]
            # Reject 1-letter drift (manish→manisha).
            if len(rest) <= 1:
                return "none"
            return "prefix_compact"
        if any(token == parts.norm for token in c.split()):
            return "token"
        # Whole-phrase containment only — not "manish" inside "manisha".
        if len(parts.norm) >= 4 and f" {parts.norm} " in f" {c} ":
            return "contains"
        return "none"

    def _score_parts(
        self,
        parts: _QueryParts,
        label: str,
        description: str | None,
        *,
        source: str,
        ticker: str | None = None,
        domain: str | None = None,
        exact_domain: bool = False,
    ) -> dict[str, Any]:
        kind = self._classify_match(parts, label, ticker=ticker)
        if kind == "none":
            return {"confidence": 0.0, "match_kind": kind}

        c = normalize_name(label)
        c_compact = re.sub(r"[^a-z0-9]", "", c)
        coverage = len(parts.compact) / max(len(c_compact), 1)

        if kind == "exact":
            score = 0.97
        elif kind == "brand_suffix":
            score = 0.94
        elif kind == "ticker":
            score = 0.93
        elif kind == "prefix_words":
            # "red" → "red hat", "pink" → "pink lily"
            score = 0.58 + min(0.28, coverage * 0.36)
            if len(parts.norm) >= 4:
                score += 0.04
        elif kind == "prefix_compact":
            # "accent" → "accenture"; weaker than word-boundary prefixes for short stems.
            score = 0.50 + min(0.28, coverage * 0.40)
            if len(parts.norm) >= 4 and coverage >= 0.55:
                score += 0.12  # strong stem continuation (accent→accenture)
            if len(parts.norm) <= 3:
                score *= 0.85
            # Lookalike shells of an already-complete query (Redfin→REDFINCAS).
            if len(parts.norm) >= 6 and coverage < 0.75 and " " not in c:
                score *= 0.72
        elif kind == "token":
            score = 0.48
        else:  # contains — too weak for the tightened suggest floor
            score = 0.38

        # Short bare exact labels ("Pink") should rank under multi-word extensions.
        if kind == "exact" and len(parts.tokens) == 1 and len(parts.norm) <= 4 and " " not in c:
            score *= 0.78

        # Source / evidence adjustments (applied once, not stacked ad hoc).
        company_desc = description_looks_like_company(description)
        if source == "wikidata":
            score += 0.06 if company_desc else -0.25
        elif source == "wikipedia":
            if company_desc:
                score += 0.08
            elif kind == "exact":
                score += 0.04
            else:
                score -= 0.12
        elif source == "clearbit":
            if exact_domain:
                score = max(score, 0.99)
                kind = "exact"
            elif domain and self._domain_supports_query(parts, domain):
                score += 0.05
                host = re.sub(r"[^a-z0-9]", "", domain.split(".")[0].lower())
                # accenture.com for query "accent" is a high-quality brand signal.
                if kind == "prefix_compact" and host.startswith(parts.compact) and len(host) <= len(parts.compact) + 4:
                    score += 0.08
            else:
                score += 0.02
            if " " in label and kind == "prefix_words":
                score += 0.04
        elif source == "yahoo":
            if ticker and parts.is_ticker:
                score += 0.04
            elif company_desc:
                score += 0.03
            elif ticker and not parts.is_ticker:
                # Bare equity shell without a real name match stays weak.
                if kind in {"contains", "token"}:
                    score *= 0.45

        # Keep short ticker/exact/brand+suffix hits (q2 → Q2 Holdings); crush other 2-char noise.
        if len(parts.norm) <= 2 and kind not in {"exact", "ticker", "brand_suffix"}:
            score *= 0.35

        return {
            "confidence": round(max(0.0, min(1.0, score)), 3),
            "match_kind": kind,
        }

    def _score(
        self,
        query: str,
        label: str,
        description: str | None,
        *,
        source: str,
        ticker: str | None = None,
    ) -> float:
        """Back-compat helper for unit tests."""
        return self._score_parts(
            self._query_parts(query), label, description, source=source, ticker=ticker
        )["confidence"]

    def _looks_like_ticker_query(self, query: str) -> bool:
        return bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,5}", query.strip()))

    def _strong_name_relation(self, parts: _QueryParts | str, label: str) -> bool:
        if isinstance(parts, str):
            parts = self._query_parts(parts)
        return self._classify_match(parts, label) != "none"

    def is_company_grade(self, suggestion: CompanySuggestion) -> bool:
        return self._is_company_grade(suggestion)

    def _is_company_grade(self, suggestion: CompanySuggestion) -> bool:
        if description_is_rejected(suggestion.description):
            return False
        if description_looks_like_company(suggestion.description):
            return True
        if suggestion.source == "wikipedia":
            # Exact Wikipedia title hits (SpaceXAI) are acceptable with thin/empty snippets,
            # but never when the snippet is an explicit non-company page.
            name = normalize_name(suggestion.name)
            return bool(name) and (
                suggestion.match_kind in {"exact", "brand_suffix"} or len(name) >= 5
            )
        if suggestion.source == "clearbit":
            name = normalize_name(suggestion.name)
            return bool(name) and (len(name.split()) >= 2 or len(name) >= 5)
        if suggestion.source == "yahoo" and suggestion.ticker:
            name = normalize_name(suggestion.name)
            return bool(name) and (len(name.split()) >= 2 or len(name) >= 6)
        return False

    def _listing_rank(self, suggestion: CompanySuggestion) -> int:
        """Prefer primary US listings over foreign dual-listings (QTWO over 0Q2.F)."""
        loc = (suggestion.location or "").upper()
        ticker = (suggestion.ticker or "").upper()
        if any(tag in loc for tag in ("NYSE", "NASDAQ", "NMS", "NGM", "NYQ")):
            return 3
        if ticker and not re.match(r"^\d", ticker) and "." not in ticker:
            return 2
        if ticker and not re.match(r"^\d", ticker):
            return 1
        return 0

    def _is_brand_with_corp_noise(self, query_norm: str, label_norm: str) -> bool:
        """True for Nestlé S.A. / Microsoft Corporation vs query nestle / microsoft."""
        if not query_norm or not label_norm.startswith(query_norm):
            return False
        if label_norm == query_norm:
            return False
        rest = label_norm[len(query_norm) :].strip()
        if not rest:
            return False
        tokens = rest.split()
        if not tokens or not all(tok in _CORP_SUFFIX_TOKENS for tok in tokens):
            return False
        # "Micro" + "Group" is too weak for short stems.
        if len(query_norm) < 6 and tokens == ["group"]:
            return False
        return True

    def _is_query_plus_corp_suffix(self, parts: _QueryParts | str, label: str) -> bool:
        """True when the display name is the query plus only legal/corp tokens.

        Needed because normalize_name() strips 'holdings'/'inc', collapsing
        'Q2 Holdings, Inc.' to 'q2' and hiding the brand-suffix structure.
        """
        if isinstance(parts, str):
            parts = self._query_parts(parts)
        if not parts.norm or not label:
            return False
        tokens = tuple(re.findall(r"[a-z0-9]+", label.lower()))
        if not tokens or tokens[0] != parts.norm:
            return False
        extras = tokens[1:]
        return bool(extras) and all(tok in _CORP_SUFFIX_TOKENS for tok in extras)

    def _is_exact_match(self, parts: _QueryParts | str, suggestion: CompanySuggestion) -> bool:
        if isinstance(parts, str):
            parts = self._query_parts(parts)
        # Always classify against the current query — never trust a stale match_kind.
        kind = self._classify_match(parts, suggestion.name, ticker=suggestion.ticker)
        return kind in {"exact", "ticker", "brand_suffix"}

    def _should_auto_analyze(
        self,
        parts: _QueryParts | str,
        chosen: CompanySuggestion,
        company_grade: list[CompanySuggestion],
    ) -> bool:
        """Auto-run only for high-confidence exact / ticker / brand-suffix hits."""
        if isinstance(parts, str):
            parts = self._query_parts(parts)

        if not self._is_exact_match(parts, chosen):
            return False
        if chosen.confidence < EXACT_CONFIDENCE:
            return False
        if description_is_rejected(chosen.description):
            return False

        if parts.is_ticker:
            return True

        # "Bain & Company" → normalize collapses to "bain", but the raw typed tokens
        # still match the suggestion — treat as a full-name exact hit.
        raw_tokens = tuple(re.findall(r"[a-z0-9]+", parts.raw.lower()))
        label_tokens = tuple(re.findall(r"[a-z0-9]+", chosen.name.lower()))
        if raw_tokens and raw_tokens == label_tokens:
            return True

        # Multi-word exact queries are unambiguous enough.
        if len(parts.tokens) >= 2:
            return True

        kind = chosen.match_kind or self._classify_match(parts, chosen.name, chosen.ticker)
        if kind == "exact":
            # Short one-word generics ("pink", "red") with stronger multi-word
            # extensions should stay in suggestion mode, not auto-analyze.
            if len(parts.tokens) == 1 and len(parts.norm) <= 5:
                extensions = [
                    item
                    for item in company_grade
                    if item is not chosen
                    and item.confidence >= SUGGEST_CONFIDENCE
                    and (
                        item.match_kind == "prefix_words"
                        or normalize_name(item.name).startswith(parts.norm + " ")
                    )
                ]
                if extensions:
                    return False
            if chosen.source == "clearbit":
                host = re.sub(r"[^a-z0-9]", "", ((chosen.location or "").split(".")[0]).lower())
                return len(parts.compact) >= 5 and host == parts.compact
            if chosen.source in {"wikidata", "yahoo", "wikipedia"}:
                if len(parts.norm) < 4:
                    return False
                if description_looks_like_company(chosen.description) or bool(chosen.ticker):
                    return True
                # Exact Wikipedia title for a longer brand (SpaceXAI) is enough to proceed.
                return chosen.source == "wikipedia" and len(parts.compact) >= 6
            return False

        if kind == "brand_suffix":
            # Short stems ("bain") stay in suggestion mode so Bain Capital can compete.
            # Full legal names are handled above via raw token equality.
            if len(parts.norm) < 6 and len(raw_tokens) < 2:
                return False
            # Require a clear lead over non-exact rivals.
            rivals = [
                item
                for item in company_grade
                if item is not chosen
                and item.confidence >= SUGGEST_CONFIDENCE
                and not self._is_exact_match(parts, item)
            ]
            if rivals and (chosen.confidence - rivals[0].confidence) < EXACT_GAP:
                return False
            return True

        if kind == "ticker":
            return True
        return False

    def _is_useful_suggestion(self, parts: _QueryParts | str, suggestion: CompanySuggestion) -> bool:
        if isinstance(parts, str):
            parts = self._query_parts(parts)
        name = normalize_name(suggestion.name)
        if not name:
            return False
        kind = suggestion.match_kind or self._classify_match(
            parts, suggestion.name, suggestion.ticker
        )
        if kind not in _STRONG_SUGGEST_KINDS:
            return False
        # Brand+corp forms ("Q2 Holdings, Inc.") stay suggestable even when normalize collapses.
        if kind == "brand_suffix" or self._is_query_plus_corp_suffix(parts, suggestion.name):
            return True
        # Prefer real extensions over a bare same-token echo for short queries.
        if kind == "exact" and len(parts.tokens) == 1 and len(parts.norm) <= 4 and name == parts.norm:
            return suggestion.confidence >= 0.85
        return True

    def to_dict(self, resolution: CompanyResolution) -> dict[str, Any]:
        return {
            "query": resolution.query,
            "status": resolution.status,
            "confidence": round(resolution.confidence, 3),
            "matched_name": resolution.matched_name,
            "message": resolution.message,
            "suggestions": [
                {
                    "name": item.name,
                    "description": item.description,
                    "confidence": item.confidence,
                    "source": item.source,
                    "ticker": item.ticker,
                    "location": item.location,
                    "match_kind": item.match_kind,
                }
                for item in resolution.suggestions
            ],
        }
