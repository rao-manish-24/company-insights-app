"""The Fortune 500 must resolve even with every upstream down; junk must not."""

import pytest

from app.core.exceptions import BadRequestError
from app.core.rate_limit import lookup_cache
from app.data.fortune500 import FORTUNE500
from app.services.company_lookup_service import (
    _COMPANY_ALIASES,
    _KNOWN_STEM_COMPANIES,
    CompanyLookupService,
)
from app.services.company_validation import (
    assert_valid_company,
    description_is_rejected,
    profile_has_company_signal,
    stemmed_tokens,
)
from app.services.market_data_service import MarketDataService

JUNK = [
    "hhhhhh",
    "asdfgh",
    "qwerty",
    "zxcvbn",
    "jkjkjk",
    "aaaa",
    "LOLzera",
    "Zentara Dynamics",
]
# Ordinary words and given names that an auto-generated alias list would have
# wrongly claimed for Texas Instruments, Robert Half, Discover Financial, etc.
NOT_COMPANIES = ["Texas", "Robert", "Peter", "Discover", "Fortune", "Henry"]


@pytest.fixture
def offline() -> CompanyLookupService:
    """Lookup with Clearbit, Wikidata, Wikipedia and Yahoo all unavailable."""
    # The resolve cache is process-wide; other tests seed it with stub payloads.
    lookup_cache.clear()
    service = CompanyLookupService.__new__(CompanyLookupService)
    service._clearbit_candidates = lambda parts: []  # type: ignore[method-assign]
    service._collect_candidates = lambda parts: []  # type: ignore[method-assign]
    return service


def _resolves(service: CompanyLookupService, query: str) -> str:
    resolution = service.resolve(query)
    assert resolution.status == "exact", f"{query}: {resolution.status}"
    assert resolution.matched_name, query
    # Registry-grade, so a throttled upstream cannot invalidate it later.
    assert resolution.verified is True, query
    assert_valid_company(
        resolution.matched_name,
        profile={},
        market={},
        identity_verified=resolution.verified,
        upstream_degraded=False,
        articles=[],
    )
    return resolution.matched_name


def test_roster_is_complete() -> None:
    assert len(FORTUNE500) == 500
    assert len({name for name, _, _ in FORTUNE500}) == 500


def test_every_alias_points_at_a_real_roster_entry() -> None:
    names = {value[0] for value in _KNOWN_STEM_COMPANIES.values()}
    assert [alias for alias, target in _COMPANY_ALIASES.items() if target not in names] == []


@pytest.mark.parametrize("company", [name for name, _, _ in FORTUNE500])
def test_fortune500_resolves_with_all_upstreams_down(
    offline: CompanyLookupService, company: str
) -> None:
    _resolves(offline, company)


@pytest.mark.parametrize("alias", sorted(_COMPANY_ALIASES))
def test_aliases_resolve_with_all_upstreams_down(
    offline: CompanyLookupService, alias: str
) -> None:
    assert _resolves(offline, alias) == _KNOWN_STEM_COMPANIES[stemmed_tokens(alias)][0]


@pytest.mark.parametrize("query", JUNK + NOT_COMPANIES)
def test_junk_never_resolves(offline: CompanyLookupService, query: str) -> None:
    resolution = offline.resolve(query)
    assert resolution.status != "exact", f"{query} resolved to {resolution.matched_name!r}"
    assert resolution.verified is False


def test_government_and_university_domains_are_not_companies() -> None:
    """Clearbit lists texas.gov and tamu.edu as companies; we must not."""
    service = CompanyLookupService.__new__(CompanyLookupService)
    service = CompanyLookupService.__new__(CompanyLookupService)
    out: list = []
    service._ingest_clearbit_rows(
        service._query_parts("Texas Instruments"),
        [
            {"name": "Texas Instruments", "domain": "texas.gov"},
            {"name": "Texas Instruments", "domain": "tamu.edu"},
            {"name": "Texas Instruments", "domain": "ti.com"},
        ],
        out=out,
        seen_domains=set(),
    )
    assert [item.location for item in out] == ["ti.com"]


def test_founding_date_alone_is_not_a_company_signal() -> None:
    """Cities and countries have an inception year too (this let London through)."""
    assert profile_has_company_signal({"founded": "0047"}) is False
    assert profile_has_company_signal({"founded": "1975", "headquarters": "Westport"}) is True
    assert profile_has_company_signal({"employees": "10,000"}) is True


def test_place_descriptions_are_rejected() -> None:
    for desc in (
        "capital and largest city of England and the United Kingdom",
        "state of the United States",
        "city in California",
    ):
        assert description_is_rejected(desc) is True
    assert description_is_rejected("multinational technology company") is False


def test_private_firms_never_borrow_an_unrelated_ticker() -> None:
    """Searching Yahoo for "PwC" returns an unrelated PWC listing."""
    service = MarketDataService()
    for name in ("PwC", "Deloitte", "McKinsey & Company", "Bain & Company", "SpaceX"):
        assert service._is_known_private(name) is True
    assert service._is_known_private("Walmart") is False


@pytest.mark.parametrize("query", JUNK)
def test_junk_is_rejected_even_when_upstreams_are_throttled(query: str) -> None:
    """A parked domain must not inherit the rate-limit benefit of the doubt."""
    with pytest.raises(BadRequestError):
        assert_valid_company(
            query,
            profile={},
            market={},
            identity_verified=False,
            upstream_degraded=True,
            articles=[],
        )
