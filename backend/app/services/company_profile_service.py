"""Fetch public company facts from Wikidata + Wikipedia key people (free, no API key)."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any
from urllib.parse import quote

from app.core.config import Settings, get_settings
from app.core.http import get_http_client, get_json
from app.core.rate_limit import profile_cache

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

# Wikidata property ids
P_INCEPTION = "P571"
P_HQ = "P159"
P_EMPLOYEES = "P1128"
P_PARENT = "P749"
P_CEO = "P169"
P_CHAIR = "P488"
P_REVENUE = "P2139"
P_OPERATING_INCOME = "P3362"
P_TOTAL_ASSETS = "P2403"

ROLE_PROPERTIES: list[tuple[str, str]] = [
    ("CEO", P_CEO),
]

# Only the CEO is shown. Other officers are inconsistently recorded upstream, so
# they were mostly rendering as "Not available" and adding noise to the brief.
KEY_PEOPLE_ROLES = ("CEO",)

# Map Wikipedia role phrases → our UI roles (order matters: more specific first).
_WIKI_ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CEO", re.compile(r"\b(ceo|chief\s+executive(\s+officer)?|chief\s+exec)\b", re.I)),
    ("COO", re.compile(r"\b(coo|chief\s+operating(\s+officer)?)\b", re.I)),
    ("CFO", re.compile(r"\b(cfo|chief\s+financial(\s+officer)?)\b", re.I)),
    ("CBO", re.compile(r"\b(cbo|chief\s+business(\s+officer)?)\b", re.I)),
    (
        "Vice President",
        re.compile(r"\b(vice[\s-]?president|evp|svp|executive\s+vice\s+president)\b", re.I),
    ),
]

_INFOBOX_FIELD_ROLES: list[tuple[str, tuple[str, ...]]] = [
    ("CEO", ("ceo", "chief_executive_officer", "chief_executive")),
    ("COO", ("coo", "chief_operating_officer")),
    ("CFO", ("cfo", "chief_financial_officer", "finance_director")),
    ("CBO", ("cbo", "chief_business_officer")),
    ("Vice President", ("vice_president", "vp")),
]

_LINK_RE = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_WS_RE = re.compile(r"\s+")


def empty_profile() -> dict[str, Any]:
    return {
        "founded": None,
        "headquarters": None,
        "employees": None,
        "parent_company": None,
        "revenue": None,
        "operating_income": None,
        "total_assets": None,
        "key_people": [{"role": role, "name": None} for role in KEY_PEOPLE_ROLES],
        "source": None,
        "source_url": None,
        "wikipedia_url": None,
        "market": None,
    }


class CompanyProfileService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = get_http_client()
        # True when Wikidata/Wikipedia refused us (403/429/5xx) during the last fetch.
        self.last_degraded = False

    def close(self) -> None:
        """No-op: the HTTP client is shared process-wide and closed at shutdown."""

    def fetch_profile(self, company_name: str) -> dict[str, Any]:
        self.last_degraded = False
        cache_key = f"profile:{' '.join(company_name.strip().lower().split())}"
        cached = profile_cache.get(cache_key)
        if isinstance(cached, dict):
            logger.info("Company profile cache hit company=%r", company_name)
            return copy.deepcopy(cached)

        profile = empty_profile()
        try:
            qid = self._search_entity(company_name)
            if not qid:
                logger.info("Wikidata: no entity for company=%r", company_name)
                # Still try Wikipedia-only key people for well-known brands.
                wiki_people, wiki_url = self._wikipedia_key_people(company_name, entity=None)
                if any(wiki_people.values()):
                    profile["key_people"] = [
                        {"role": role, "name": wiki_people.get(role)} for role in KEY_PEOPLE_ROLES
                    ]
                    profile["source"] = "Wikipedia"
                    profile["wikipedia_url"] = wiki_url
                    profile["source_url"] = wiki_url
                return self._store_profile(cache_key, profile)

            entity = self._get_entity(qid)
            if not entity:
                stale = profile_cache.get(cache_key, allow_stale=True)
                if isinstance(stale, dict):
                    logger.info("Company profile stale cache after empty entity company=%r", company_name)
                    return copy.deepcopy(stale)
                return profile

            claims = entity.get("claims") or {}
            label = ((entity.get("labels") or {}).get("en") or {}).get("value") or company_name
            description = ((entity.get("descriptions") or {}).get("en") or {}).get("value")

            # Batch-resolve entity labels (HQ/parent/CEO/units) — one Wikidata call.
            label_qids: list[str] = []
            for prop in (P_HQ, P_PARENT, *(p for _, p in ROLE_PROPERTIES)):
                qid = self._claim_entity_id(claims.get(prop))
                if qid:
                    label_qids.append(qid)
            for prop in (P_REVENUE, P_OPERATING_INCOME, P_TOTAL_ASSETS, P_EMPLOYEES):
                unit_qid = self._claim_unit_id(claims.get(prop))
                if unit_qid and unit_qid != "1":
                    label_qids.append(unit_qid)
            labels = self._entity_labels_batch(label_qids)

            profile["founded"] = self._format_time_claim(claims.get(P_INCEPTION))
            hq_qid = self._claim_entity_id(claims.get(P_HQ))
            profile["headquarters"] = labels.get(hq_qid) if hq_qid else None
            profile["employees"] = self._format_quantity_claim(
                claims.get(P_EMPLOYEES),
                unit_suffix=" employees",
                unit_labels=labels,
            )
            parent_qid = self._claim_entity_id(claims.get(P_PARENT))
            profile["parent_company"] = labels.get(parent_qid) if parent_qid else None
            profile["revenue"] = self._format_quantity_claim(
                claims.get(P_REVENUE), money=True, unit_labels=labels
            )
            profile["operating_income"] = self._format_quantity_claim(
                claims.get(P_OPERATING_INCOME), money=True, unit_labels=labels
            )
            profile["total_assets"] = self._format_quantity_claim(
                claims.get(P_TOTAL_ASSETS), money=True, unit_labels=labels
            )

            people: dict[str, str | None] = {role: None for role in KEY_PEOPLE_ROLES}
            for role, prop in ROLE_PROPERTIES:
                person_qid = self._claim_entity_id(claims.get(prop))
                if person_qid and labels.get(person_qid):
                    people[role] = labels[person_qid]

            # Fill gaps from the English Wikipedia infobox when Wikidata has no CEO claim.
            wiki_people, wiki_url = self._wikipedia_key_people(company_name, entity=entity)
            wiki_filled = False
            for role in KEY_PEOPLE_ROLES:
                if people.get(role):
                    continue
                fill = wiki_people.get(role)
                if fill:
                    people[role] = fill
                    wiki_filled = True

            profile["key_people"] = [{"role": role, "name": people[role]} for role in KEY_PEOPLE_ROLES]
            profile["source"] = "Wikidata + Wikipedia" if wiki_filled else "Wikidata"
            profile["source_url"] = f"https://www.wikidata.org/wiki/{qid}"
            profile["wikipedia_url"] = wiki_url
            profile["matched_label"] = label
            profile["matched_description"] = description

            logger.info(
                "Company profile company=%r qid=%s founded=%s hq=%s ceo=%s wiki_fill=%s",
                company_name,
                qid,
                profile["founded"],
                profile["headquarters"],
                people.get("CEO"),
                wiki_filled,
            )
            return self._store_profile(cache_key, profile)
        except Exception:
            logger.exception("Company profile fetch failed company=%r", company_name)
            stale = profile_cache.get(cache_key, allow_stale=True)
            if isinstance(stale, dict):
                logger.info("Company profile stale cache after error company=%r", company_name)
                return copy.deepcopy(stale)
            # Wikidata rate-limits / outages should not block Wikipedia key-people fill.
            try:
                wiki_people, wiki_url = self._wikipedia_key_people(company_name, entity=None)
                if any(wiki_people.values()):
                    profile["key_people"] = [
                        {"role": role, "name": wiki_people.get(role)} for role in KEY_PEOPLE_ROLES
                    ]
                    profile["source"] = "Wikipedia"
                    profile["wikipedia_url"] = wiki_url
                    profile["source_url"] = wiki_url
                    return self._store_profile(cache_key, profile)
            except Exception:
                logger.warning(
                    "Wikipedia key-people fallback failed company=%r", company_name, exc_info=True
                )
            return profile

    def _store_profile(self, cache_key: str, profile: dict[str, Any]) -> dict[str, Any]:
        # Only cache populated profiles so empty 429 responses do not poison the key.
        if profile.get("source") or profile.get("matched_label") or profile.get("founded"):
            ttl = max(60, self.settings.upstream_cache_minutes * 60)
            profile_cache.set(cache_key, copy.deepcopy(profile), ttl, stale_seconds=ttl * 3)
        return profile

    def _get_json_tracked(self, url: str, *, params: dict[str, Any]) -> dict[str, Any] | None:
        payload = self._get_json(url, params=params)
        if payload is None:
            self.last_degraded = True
        return payload

    def _get_json(self, url: str, *, params: dict[str, Any]) -> dict[str, Any] | None:
        """GET JSON; refusals/outages return None so callers can fall back."""
        return get_json(url, params=params, client=self._client, label="company profile")

    def _wikipedia_key_people(
        self,
        company_name: str,
        *,
        entity: dict[str, Any] | None,
    ) -> tuple[dict[str, str], str | None]:
        """Return role→name from Wikipedia infobox only (never invents)."""
        try:
            title = self._wikipedia_title(company_name, entity=entity)
            if not title:
                return {}, None
            wikitext = self._fetch_wikipedia_wikitext(title)
            if not wikitext:
                return {}, None
            people = self._parse_key_people_from_wikitext(wikitext)
            url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            if people:
                logger.info(
                    "Wikipedia key people company=%r title=%r roles=%s",
                    company_name,
                    title,
                    sorted(people.keys()),
                )
            return people, url
        except Exception:
            logger.warning("Wikipedia key people fetch failed company=%r", company_name, exc_info=True)
            return {}, None

    def _wikipedia_title(
        self,
        company_name: str,
        *,
        entity: dict[str, Any] | None,
    ) -> str | None:
        if entity:
            sitelinks = entity.get("sitelinks") or {}
            enwiki = sitelinks.get("enwiki") or {}
            title = (enwiki.get("title") or "").strip()
            if title:
                return title

        # Fallback: Wikipedia search, prefer company/org-ish titles.
        payload = self._get_json_tracked(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": company_name,
                "srlimit": 5,
                "format": "json",
            },
        )
        if not payload:
            return None
        hits = ((payload.get("query") or {}).get("search")) or []
        if not hits:
            return None
        from app.services.company_validation import names_align

        for hit in hits:
            title = (hit.get("title") or "").strip()
            if title and names_align(company_name, title):
                return title
        return (hits[0].get("title") or "").strip() or None

    def _fetch_wikipedia_wikitext(self, title: str) -> str | None:
        payload = self._get_json_tracked(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "rvlimit": 1,
                "titles": title,
                "redirects": 1,
                "format": "json",
            },
        )
        if not payload:
            return None
        pages = ((payload.get("query") or {}).get("pages")) or {}
        for page in pages.values():
            if page.get("missing") is not None:
                continue
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            slots = revisions[0].get("slots") or {}
            main = slots.get("main") or {}
            content = main.get("*")
            if isinstance(content, str) and content.strip():
                return content
            # Older API shape
            legacy = revisions[0].get("*")
            if isinstance(legacy, str) and legacy.strip():
                return legacy
        return None

    def _parse_key_people_from_wikitext(self, wikitext: str) -> dict[str, str]:
        """Extract CEO/COO/CFO/CBO/VP from company infobox fields / key_people lists."""
        found: dict[str, str] = {}
        infobox = self._extract_infobox(wikitext)
        if not infobox:
            return found

        fields = self._parse_infobox_fields(infobox)

        # Dedicated role fields first (ceo=, cfo=, …).
        for role, keys in _INFOBOX_FIELD_ROLES:
            if role in found:
                continue
            for key in keys:
                raw = fields.get(key)
                if not raw:
                    continue
                name = self._first_person_name(raw)
                if name:
                    found[role] = name
                    break

        # Then parse free-form key_people / leaders lists.
        for key in ("key_people", "keypeople", "leaders", "leadership"):
            blob = fields.get(key)
            if not blob:
                continue
            for name, role_hint in self._iter_people_role_pairs(blob):
                role = self._match_role(role_hint)
                if role and role not in found and name:
                    found[role] = name

        return found

    def _extract_infobox(self, wikitext: str) -> str | None:
        match = re.search(r"\{\{\s*Infobox\s+company\b", wikitext, re.I)
        if not match:
            # Some pages use Infobox organization / bank / etc.
            match = re.search(r"\{\{\s*Infobox\s+(organization|bank|financial|airline)\b", wikitext, re.I)
        if not match:
            return None
        start = match.start()
        depth = 0
        i = start
        while i < len(wikitext) - 1:
            chunk = wikitext[i : i + 2]
            if chunk == "{{":
                depth += 1
                i += 2
                continue
            if chunk == "}}":
                depth -= 1
                i += 2
                if depth == 0:
                    return wikitext[start:i]
                continue
            i += 1
        return None

    def _parse_infobox_fields(self, infobox: str) -> dict[str, str]:
        """Parse `| key = value` pairs; ignore `|` separators inside nested templates."""
        body = infobox.strip()
        if body.startswith("{{"):
            body = body[2:]
        if body.endswith("}}"):
            body = body[:-2]

        fields: dict[str, str] = {}
        depth = 0
        i = 0
        current_key: str | None = None
        value_start = 0
        n = len(body)

        while i < n:
            if body.startswith("{{", i):
                depth += 1
                i += 2
                continue
            if body.startswith("}}", i):
                depth = max(0, depth - 1)
                i += 2
                continue
            if depth == 0 and body[i] == "|":
                match = re.match(r"\|\s*([A-Za-z0-9_ +/\-]+?)\s*=\s*", body[i:])
                if match:
                    if current_key is not None:
                        fields[current_key] = body[value_start:i].strip()
                    current_key = re.sub(r"[\s]+", "_", match.group(1).strip().lower())
                    i += match.end()
                    value_start = i
                    continue
            i += 1

        if current_key is not None:
            fields[current_key] = body[value_start:].strip()
        return fields

    def _iter_people_role_pairs(self, blob: str) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        # Split common list separators used in infoboxes.
        chunks = re.split(r"<br\s*/?>|\n|\||(?<=\))\s*;\s*", blob)
        if len(chunks) <= 1:
            chunks = re.split(r"\n|(?<=\))\s*,\s*(?=\[\[)", blob)

        for chunk in chunks:
            text = chunk.strip()
            if not text or text.lower() in {"ubl", "unbulleted list", "plainlist", "flatlist"}:
                continue
            name = self._first_person_name(text)
            if not name:
                continue
            # Role hint is usually in parentheses after the name.
            role_hint = text
            paren = re.search(r"\(([^)]+)\)", text)
            if paren:
                role_hint = paren.group(1)
            pairs.append((name, role_hint))
        return pairs

    def _match_role(self, role_hint: str) -> str | None:
        for role, pattern in _WIKI_ROLE_PATTERNS:
            if pattern.search(role_hint or ""):
                return role
        return None

    def _first_person_name(self, value: str) -> str | None:
        if not value:
            return None
        link = _LINK_RE.search(value)
        if link:
            # Prefer display text, else link target; drop disambiguation crumbs.
            raw = (link.group(2) or link.group(1) or "").strip()
        else:
            cleaned = _TEMPLATE_RE.sub(" ", value)
            cleaned = _HTML_TAG_RE.sub(" ", cleaned)
            cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
            cleaned = cleaned.replace("'", " ").replace('"', " ")
            raw = cleaned.strip(" |•-–—")
        raw = _WS_RE.sub(" ", raw).strip(" ,;")
        if not raw or len(raw) < 2 or len(raw) > 80:
            return None
        # Reject obvious non-person leftovers.
        if re.search(r"\{\{|https?://|^\d+$", raw, re.I):
            return None
        return raw

    def _search_entity(self, company_name: str) -> str | None:
        from app.services.company_validation import (
            description_looks_like_company,
            names_align,
        )

        payload = self._get_json_tracked(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": company_name,
                "language": "en",
                "type": "item",
                "limit": 8,
                "format": "json",
            },
        )
        if not payload:
            return None
        results = payload.get("search") or []
        if not results:
            return None

        # Only accept business-like hits whose label actually matches the query.
        # Never fall back to results[0] (that mapped "k"→kelvin, "m"→metre).
        for item in results:
            label = item.get("label") or ""
            desc = item.get("description") or ""
            if not names_align(company_name, label):
                continue
            if description_looks_like_company(desc):
                return item.get("id")

        for item in results:
            label = item.get("label") or ""
            if names_align(company_name, label):
                # Keep a weaker same-name hit; validation later still requires company signals.
                return item.get("id")
        return None

    def _get_entity(self, qid: str) -> dict[str, Any] | None:
        payload = self._get_json_tracked(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims|labels|descriptions|sitelinks",
                "languages": "en",
                "sitefilter": "enwiki",
                "format": "json",
            },
        )
        if not payload:
            return None
        return (payload.get("entities") or {}).get(qid)

    def _mainsnak_value(self, claim_list: list[dict[str, Any]] | None) -> Any | None:
        if not claim_list:
            return None
        # Prefer preferred rank, else first normal
        ordered = sorted(
            claim_list,
            key=lambda c: 0 if c.get("rank") == "preferred" else 1 if c.get("rank") == "normal" else 2,
        )
        snak = (ordered[0].get("mainsnak") or {})
        if snak.get("snaktype") != "value":
            return None
        return (snak.get("datavalue") or {}).get("value")

    def _format_time_claim(self, claim_list: list[dict[str, Any]] | None) -> str | None:
        value = self._mainsnak_value(claim_list)
        if not isinstance(value, dict):
            return None
        time_str = value.get("time") or ""
        # +1975-04-04T00:00:00Z
        cleaned = time_str.lstrip("+").split("T")[0]
        if cleaned.endswith("-00-00"):
            return cleaned[:4]
        if cleaned[5:7] == "00":
            return cleaned[:4]
        if cleaned.endswith("-00"):
            return cleaned[:7]
        return cleaned

    def _format_quantity_claim(
        self,
        claim_list: list[dict[str, Any]] | None,
        *,
        money: bool = False,
        unit_suffix: str = "",
        unit_labels: dict[str, str] | None = None,
    ) -> str | None:
        value = self._mainsnak_value(claim_list)
        if not isinstance(value, dict):
            return None
        try:
            amount = float(str(value.get("amount", "")).lstrip("+"))
        except ValueError:
            return None

        unit_id = self._claim_unit_id(claim_list)
        if unit_labels is not None:
            unit_label = unit_labels.get(unit_id) if unit_id and unit_id != "1" else None
        else:
            unit_label = self._entity_label(unit_id) if unit_id and unit_id != "1" else None
        pretty = self._human_number(amount)

        if money:
            currency = unit_label or "USD"
            # Prefer ISO-ish short codes when Wikidata returns long names
            currency_map = {
                "United States dollar": "USD",
                "euro": "EUR",
                "pound sterling": "GBP",
                "Japanese yen": "JPY",
                "Swiss franc": "CHF",
            }
            currency = currency_map.get(currency, currency)
            return f"{pretty} {currency}"

        if unit_suffix:
            return f"{pretty}{unit_suffix}"
        if unit_label:
            return f"{pretty} {unit_label}"
        return pretty

    def _claim_entity_id(self, claim_list: list[dict[str, Any]] | None) -> str | None:
        value = self._mainsnak_value(claim_list)
        if not isinstance(value, dict):
            return None
        qid = value.get("id")
        return str(qid) if qid else None

    def _claim_unit_id(self, claim_list: list[dict[str, Any]] | None) -> str | None:
        value = self._mainsnak_value(claim_list)
        if not isinstance(value, dict):
            return None
        unit = value.get("unit") or ""
        if unit.startswith("http://www.wikidata.org/entity/"):
            return unit.rsplit("/", 1)[-1]
        return None

    def _resolve_entity_claim(self, claim_list: list[dict[str, Any]] | None) -> str | None:
        qid = self._claim_entity_id(claim_list)
        if not qid:
            return None
        return self._entity_label(qid)

    def _entity_labels_batch(self, qids: list[str]) -> dict[str, str]:
        unique = []
        seen: set[str] = set()
        for qid in qids:
            if not qid or qid in seen:
                continue
            seen.add(qid)
            unique.append(qid)
        if not unique:
            return {}
        payload = self._get_json(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": "|".join(unique),
                "props": "labels",
                "languages": "en",
                "format": "json",
            },
        )
        if not payload:
            return {}
        out: dict[str, str] = {}
        for qid, entity in (payload.get("entities") or {}).items():
            if not isinstance(entity, dict):
                continue
            label = ((entity.get("labels") or {}).get("en") or {}).get("value")
            if label:
                out[str(qid)] = str(label)
        return out

    def _entity_label(self, qid: str | None) -> str | None:
        if not qid:
            return None
        batched = self._entity_labels_batch([qid])
        return batched.get(qid)

    @staticmethod
    def _human_number(amount: float) -> str:
        abs_amount = abs(amount)
        sign = "-" if amount < 0 else ""
        if abs_amount >= 1_000_000_000_000:
            return f"{sign}{abs_amount / 1_000_000_000_000:.2f} trillion"
        if abs_amount >= 1_000_000_000:
            return f"{sign}{abs_amount / 1_000_000_000:.2f} billion"
        if abs_amount >= 1_000_000:
            return f"{sign}{abs_amount / 1_000_000:.2f} million"
        if abs_amount >= 1_000:
            return f"{sign}{abs_amount:,.0f}"
        if abs_amount >= 1:
            return f"{sign}{abs_amount:,.0f}"
        return f"{sign}{abs_amount}"
