from app.core.exceptions import BadRequestError
from app.services.company_validation import (
    assert_valid_company,
    looks_like_gibberish,
    names_align,
)


def test_names_align_rejects_single_letter_substring() -> None:
    assert names_align("k", "kelvin") is False
    assert names_align("m", "metre") is False
    assert names_align("Microsoft", "Microsoft Corporation") is True
    assert names_align("MSFT", "MSFT") is True
    assert names_align("Apple", "Apple Inc.") is True
    assert names_align("Apple", "Apple Hospitality REIT, Inc.") is False
    assert names_align("Tesla", "Tesla, Inc.") is True
    assert names_align("Advanced Micro Device", "Advanced Micro Devices, Inc.") is True
    assert names_align("Applied Micro Devices", "Advanced Micro Devices, Inc.") is False
    assert names_align("Google", "Alphabet Inc.") is True
    assert names_align("Facebook", "Meta Platforms, Inc.") is True


def test_assert_valid_company_accepts_google_via_alphabet_ticker() -> None:
    assert_valid_company(
        "Google",
        profile={},
        market={"ticker": "GOOGL", "name": "Alphabet Inc."},
    )


def test_assert_valid_company_allows_resolved_when_upstream_throttled() -> None:
    # Wikidata/Yahoo rate-limited after resolve already proved Siemens is a company.
    assert_valid_company(
        "Siemens",
        profile={},
        market={},
        identity_verified=True,
        upstream_degraded=True,
    )


def test_assert_valid_company_rejects_resolved_when_upstream_clean_but_empty() -> None:
    # Upstreams answered fine and found nothing — a squatted domain is not a company.
    try:
        assert_valid_company(
            "Zentara Dynamics",
            profile={},
            market={},
            identity_verified=True,
            upstream_degraded=False,
        )
        raise AssertionError("expected BadRequestError")
    except BadRequestError as exc:
        assert "Not a valid company name" in exc.detail


def test_assert_valid_company_rejects_gibberish_even_when_verified() -> None:
    for junk in ("hhhhhh", "asdfgh", "qwerty", "zxcvbn"):
        try:
            assert_valid_company(
                junk,
                profile={},
                market={},
                identity_verified=True,
                upstream_degraded=True,
            )
            raise AssertionError(f"expected BadRequestError for {junk}")
        except BadRequestError as exc:
            assert "Not a valid company name" in exc.detail


def test_assert_valid_company_accepts_news_backed_private_company() -> None:
    class _Article:
        def __init__(self, title: str, description: str) -> None:
            self.title = title
            self.description = description

    assert_valid_company(
        "Zentara Dynamics",
        profile={},
        market={},
        identity_verified=True,
        articles=[_Article("Zentara Dynamics raises Series B", "The robotics firm ...")],
    )


def test_looks_like_gibberish_keeps_real_companies() -> None:
    for junk in ("hhhhhh", "asdfgh", "qwerty", "zxcvbn", "aaaa", "abab", "lkjhgf"):
        assert looks_like_gibberish(junk) is True, junk
    for real in ("Microsoft", "Bain & Company", "IBM", "HSBC", "KPMG", "3M", "Kyndryl", "Nestlé"):
        assert looks_like_gibberish(real) is False, real


def test_assert_valid_company_rejects_given_name_even_when_verified() -> None:
    try:
        assert_valid_company(
            "Manish",
            profile={
                "matched_label": "Manish",
                "matched_description": "male given name",
            },
            market={},
            identity_verified=True,
        )
        raise AssertionError("expected BadRequestError")
    except BadRequestError as exc:
        assert "Not a valid company name" in exc.detail


def test_assert_valid_company_rejects_given_name() -> None:
    try:
        assert_valid_company(
            "Manish",
            profile={
                "matched_label": "Manish",
                "matched_description": "male given name",
            },
            market={},
        )
        raise AssertionError("expected BadRequestError")
    except BadRequestError as exc:
        assert "Not a valid company name" in exc.detail


def test_assert_valid_company_rejects_junk() -> None:
    try:
        assert_valid_company(
            "k",
            profile={"matched_label": "kelvin", "matched_description": "SI unit of temperature"},
            market={"ticker": "KRW=X", "name": "USD/KRW"},
        )
        raise AssertionError("expected BadRequestError")
    except BadRequestError as exc:
        assert "Not a valid company name" in exc.detail


def test_businessperson_description_is_not_company() -> None:
    from app.services.company_validation import description_looks_like_company

    assert description_looks_like_company(
        "Indian businessperson (born 1985, child of Gauthamchand Bhandari)"
    ) is False
    assert description_looks_like_company("American real estate brokerage") is True
    assert description_looks_like_company("multinational technology company") is True


def test_assert_valid_company_accepts_ticker() -> None:
    assert_valid_company(
        "MSFT",
        profile={},
        market={"ticker": "MSFT", "name": "Microsoft Corporation"},
    )
