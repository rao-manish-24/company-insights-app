from app.services.company_profile_service import CompanyProfileService


def test_parse_key_people_from_infobox_list() -> None:
    service = CompanyProfileService.__new__(CompanyProfileService)
    wikitext = """
{{Infobox company
| name = Example Corp
| key_people = {{unbulleted list
 | [[Ada Lovelace]] ([[Chief executive officer|CEO]])
 | [[Grace Hopper]] (CFO)
 | [[Alan Turing]] (COO)
}}
}}
"""
    people = service._parse_key_people_from_wikitext(wikitext)
    assert people["CEO"] == "Ada Lovelace"
    assert people["CFO"] == "Grace Hopper"
    assert people["COO"] == "Alan Turing"


def test_parse_key_people_from_ceo_field() -> None:
    service = CompanyProfileService.__new__(CompanyProfileService)
    wikitext = """
{{Infobox company
| ceo = [[Satya Nadella]]
| chief_financial_officer = Amy Hood
}}
"""
    people = service._parse_key_people_from_wikitext(wikitext)
    assert people["CEO"] == "Satya Nadella"
    assert people["CFO"] == "Amy Hood"


def test_parse_ignores_missing_roles() -> None:
    service = CompanyProfileService.__new__(CompanyProfileService)
    people = service._parse_key_people_from_wikitext("{{Infobox company|name=Acme}}")
    assert people == {}
