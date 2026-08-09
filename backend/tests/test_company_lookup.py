from app.services.company_lookup_service import CompanyLookupService, CompanySuggestion


def test_score_prefix_suggestions() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    pink = service._score("pink", "Pink Lily", "retail apparel company", source="wikidata")
    red = service._score("red", "Red Hat", "software company", source="wikidata")
    accent = service._score("accent", "Accenture", "consulting company", source="wikidata")
    assert pink >= 0.55
    assert red >= 0.55
    assert accent >= 0.55


def test_weak_contains_below_suggest_floor() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    weak = service._score("tech", "Global Biotech Holdings", "holding company", source="wikidata")
    assert weak < 0.55


def test_score_prefers_word_prefix_over_lookalike() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    pink_lily = service._score("pink", "Pink Lily", "retail company", source="clearbit")
    redfin = service._score("Redfin", "Redfin", "Company · redfin.com", source="clearbit")
    redfincas = service._score("Redfin", "REDFINCAS", "Company · redfincas.es", source="clearbit")
    assert pink_lily > 0.5
    assert redfin > redfincas


def test_exact_match_requires_full_name() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    suggestion = CompanySuggestion(
        name="Accenture",
        description="consulting company",
        confidence=0.9,
        source="wikidata",
        match_kind="exact",
    )
    assert service._is_exact_match("accenture", suggestion) is True
    assert service._is_exact_match("accent", suggestion) is False


def test_person_name_filter() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    assert service._looks_like_person_name("Manish Malhotra", "manish") is True
    assert service._looks_like_person_name("Pink Lily", "pink", domain="pinklily.com") is False
    assert service._looks_like_person_name("Manish Anil Gupta & Co.", "manish") is True


def test_strong_name_relation_rejects_person_drift() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    assert service._strong_name_relation("manish", "Manisha Garg") is False
    assert service._strong_name_relation("accent", "Accenture") is True
    assert service._strong_name_relation("pink", "Pink Lily") is True


def test_full_brand_name_auto_analyzes() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    redfin = CompanySuggestion(
        name="Redfin",
        description="Company · redfin.com",
        confidence=0.99,
        source="clearbit",
        location="redfin.com",
        match_kind="exact",
    )
    red_bull = CompanySuggestion(
        name="Red Bull",
        description="brand of energy drinks sold by Red Bull GmbH",
        confidence=0.99,
        source="wikidata",
        match_kind="exact",
    )
    assert service._should_auto_analyze("Redfin", redfin, [redfin]) is True
    assert service._should_auto_analyze("Red Bull", red_bull, [red_bull]) is True


def test_clearbit_search_terms_include_probes() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    terms = service._clearbit_search_terms("pink")
    assert "pink" in terms
    assert "pink lily" in terms
    assert "pink taco" in terms


def test_near_plural_matches_as_exact() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    parts = service._query_parts("Advanced Micro Device")
    assert service._classify_match(parts, "Advanced Micro Devices, Inc.", "AMD") == "exact"
    score = service._score(
        "Advanced Micro Device",
        "Advanced Micro Devices, Inc.",
        "Semiconductors · NMS",
        source="yahoo",
        ticker="AMD",
    )
    assert score >= 0.92
    assert "Advanced Micro Devices" in service._near_query_variants("Advanced Micro Device")
    fallbacks = service._known_company_fallbacks(parts)
    assert fallbacks and fallbacks[0].ticker == "AMD"


def test_bain_known_fallback_private_firm() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    for query in ("Bain", "Bain & Company"):
        parts = service._query_parts(query)
        fallbacks = service._known_company_fallbacks(parts)
        assert fallbacks, query
        assert fallbacks[0].name == "Bain & Company"
        assert fallbacks[0].ticker is None
        assert fallbacks[0].source == "wikipedia"


def test_quick_verify_accepts_known_bain() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    # Avoid network — only known stems.
    service._clearbit_candidates = lambda parts: []  # type: ignore[method-assign]
    result = service.quick_verify("Bain & Company")
    assert result is not None
    assert result[0] == "Bain & Company"


def test_bain_and_company_auto_analyzes_full_name() -> None:
    """normalize() strips 'company', but a full typed name should still auto-run."""
    service = CompanyLookupService.__new__(CompanyLookupService)
    suggestion = CompanySuggestion(
        name="Bain & Company",
        description="Company · bain.com",
        confidence=0.99,
        source="clearbit",
        location="bain.com",
        match_kind="brand_suffix",
    )
    parts = service._query_parts("Bain & Company")
    assert service._is_exact_match(parts, suggestion) is True
    assert service._should_auto_analyze(parts, suggestion, [suggestion]) is True
    # Short stem alone should stay in suggestion mode (Bain Capital, etc.).
    short = service._query_parts("Bain")
    assert service._should_auto_analyze(short, suggestion, [suggestion]) is False


def test_siemens_known_fallback_uses_stemmed_key() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    fallbacks = service._known_company_fallbacks(service._query_parts("Siemens"))
    assert fallbacks and fallbacks[0].name == "Siemens AG"
    assert fallbacks[0].ticker == "SIEGY"


def test_wikipedia_exact_brand_scores_high() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    score = service._score(
        "SpaceXAI",
        "SpaceXAI",
        "SpaceXAI (formerly xAI) is a subsidiary working in artificial intelligence",
        source="wikipedia",
    )
    assert score >= 0.92
    suggestion = CompanySuggestion(
        name="SpaceXAI",
        description="SpaceXAI (formerly xAI) is a subsidiary working in artificial intelligence",
        confidence=score,
        source="wikipedia",
        match_kind="exact",
    )
    assert service._is_company_grade(suggestion) is True
    assert service._should_auto_analyze("SpaceXAI", suggestion, [suggestion]) is True


def test_wikipedia_given_name_is_not_company_grade() -> None:
    service = CompanyLookupService.__new__(CompanyLookupService)
    suggestion = CompanySuggestion(
        name="Manish",
        description=(
            "Manish (also Maneesh) is a common Hindu masculine given name that literally "
            "means The God of the Mind"
        ),
        confidence=1.0,
        source="wikipedia",
        match_kind="exact",
    )
    assert service._is_company_grade(suggestion) is False
    assert service._should_auto_analyze("Manish", suggestion, [suggestion]) is False


def test_short_brand_with_holdings_is_brand_suffix() -> None:
    """Q2 Holdings collapses to 'q2' after normalize — still a real company suggestion."""
    service = CompanyLookupService.__new__(CompanyLookupService)
    suggestion = CompanySuggestion(
        name="Q2 Holdings, Inc.",
        description="Software—Application · NYSE",
        confidence=0.94,
        source="yahoo",
        ticker="QTWO",
        match_kind="brand_suffix",
    )
    assert service._classify_match(service._query_parts("q2"), "Q2 Holdings, Inc.", "QTWO") == (
        "brand_suffix"
    )
    assert service._is_useful_suggestion("q2", suggestion) is True
    assert service._is_exact_match("q2", suggestion) is True
    # Too short to auto-analyze; should surface as a pickable suggestion instead.
    assert service._should_auto_analyze("q2", suggestion, [suggestion]) is False
