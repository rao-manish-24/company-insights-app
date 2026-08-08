"""Fetch public company facts from Wikidata (free, no API key)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "CompanyInsights/1.1 (partner briefing prototype; educational use)"

# Wikidata property ids
P_INCEPTION = "P571"
P_HQ = "P159"
P_EMPLOYEES = "P1128"
P_PARENT = "P749"
P_CEO = "P169"
P_COO = "P1789"
P_CHAIR = "P488"
P_REVENUE = "P2139"
P_OPERATING_INCOME = "P3362"
P_TOTAL_ASSETS = "P2403"

ROLE_PROPERTIES: list[tuple[str, str]] = [
    ("CEO", P_CEO),
    ("COO", P_COO),
    ("Chairperson", P_CHAIR),
]


def empty_profile() -> dict[str, Any]:
    return {
        "founded": None,
        "headquarters": None,
        "employees": None,
        "parent_company": None,
        "revenue": None,
        "operating_income": None,
        "total_assets": None,
        "key_people": [
            {"role": "CEO", "name": None},
            {"role": "COO", "name": None},
            {"role": "CFO", "name": None},
            {"role": "CBO", "name": None},
            {"role": "Vice President", "name": None},
        ],
        "source": None,
        "source_url": None,
    }


class CompanyProfileService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = httpx.Client(
            timeout=25.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def fetch_profile(self, company_name: str) -> dict[str, Any]:
        profile = empty_profile()
        try:
            qid = self._search_entity(company_name)
            if not qid:
                logger.info("Wikidata: no entity for company=%r", company_name)
                return profile

            entity = self._get_entity(qid)
            if not entity:
                return profile

            claims = entity.get("claims") or {}
            label = ((entity.get("labels") or {}).get("en") or {}).get("value") or company_name

            profile["founded"] = self._format_time_claim(claims.get(P_INCEPTION))
            profile["headquarters"] = self._resolve_entity_claim(claims.get(P_HQ))
            profile["employees"] = self._format_quantity_claim(claims.get(P_EMPLOYEES), unit_suffix=" employees")
            profile["parent_company"] = self._resolve_entity_claim(claims.get(P_PARENT))
            profile["revenue"] = self._format_quantity_claim(claims.get(P_REVENUE), money=True)
            profile["operating_income"] = self._format_quantity_claim(claims.get(P_OPERATING_INCOME), money=True)
            profile["total_assets"] = self._format_quantity_claim(claims.get(P_TOTAL_ASSETS), money=True)

            people: dict[str, str | None] = {
                "CEO": None,
                "COO": None,
                "CFO": None,
                "CBO": None,
                "Vice President": None,
            }
            for role, prop in ROLE_PROPERTIES:
                name = self._resolve_entity_claim(claims.get(prop))
                if name:
                    people[role] = name

            # Sparse roles often live only in free text elsewhere — leave null rather than invent.
            profile["key_people"] = [{"role": role, "name": people[role]} for role in people]
            profile["source"] = "Wikidata"
            profile["source_url"] = f"https://www.wikidata.org/wiki/{qid}"
            profile["matched_label"] = label

            logger.info(
                "Wikidata profile company=%r qid=%s founded=%s hq=%s ceo=%s",
                company_name,
                qid,
                profile["founded"],
                profile["headquarters"],
                people.get("CEO"),
            )
            return profile
        except Exception:
            logger.exception("Wikidata profile fetch failed company=%r", company_name)
            return profile

    def _search_entity(self, company_name: str) -> str | None:
        response = self._client.get(
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
        response.raise_for_status()
        results = response.json().get("search") or []
        if not results:
            return None

        # Prefer business/org-like descriptions
        preferred_bits = (
            "company",
            "corporation",
            "enterprise",
            "business",
            "manufacturer",
            "technology",
            "bank",
            "group",
            "inc",
            "ltd",
        )
        for item in results:
            desc = (item.get("description") or "").lower()
            label = (item.get("label") or "").lower()
            if any(bit in desc for bit in preferred_bits) or company_name.lower() in label:
                return item.get("id")
        return results[0].get("id")

    def _get_entity(self, qid: str) -> dict[str, Any] | None:
        response = self._client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "claims|labels",
                "languages": "en",
                "format": "json",
            },
        )
        response.raise_for_status()
        return (response.json().get("entities") or {}).get(qid)

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
    ) -> str | None:
        value = self._mainsnak_value(claim_list)
        if not isinstance(value, dict):
            return None
        try:
            amount = float(str(value.get("amount", "")).lstrip("+"))
        except ValueError:
            return None

        unit_id = None
        unit = value.get("unit") or ""
        if unit.startswith("http://www.wikidata.org/entity/"):
            unit_id = unit.rsplit("/", 1)[-1]

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

    def _resolve_entity_claim(self, claim_list: list[dict[str, Any]] | None) -> str | None:
        value = self._mainsnak_value(claim_list)
        if not isinstance(value, dict):
            return None
        qid = value.get("id")
        if not qid:
            return None
        return self._entity_label(qid)

    def _entity_label(self, qid: str | None) -> str | None:
        if not qid:
            return None
        response = self._client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "props": "labels",
                "languages": "en",
                "format": "json",
            },
        )
        response.raise_for_status()
        entity = (response.json().get("entities") or {}).get(qid) or {}
        return ((entity.get("labels") or {}).get("en") or {}).get("value")

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
