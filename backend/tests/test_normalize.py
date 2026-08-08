from app.repositories.analysis_repository import normalize_company_name


def test_normalize_company_name_collapses_whitespace_and_case() -> None:
    assert normalize_company_name("  Acme   Corp ") == "acme corp"
