from __future__ import annotations

from app.geo_catalog import COUNTRIES, get_language


def test_iso_codes_are_uppercase_and_unique_alpha2():
    iso_codes = [c.iso_code for c in COUNTRIES]
    assert len(iso_codes) == len(set(iso_codes))
    for code in iso_codes:
        assert code == code.upper() and len(code) == 2 and code.isalpha()


def test_dfs_location_codes_are_unique():
    dfs_codes = [c.dfs_location_code for c in COUNTRIES]
    assert len(dfs_codes) == len(set(dfs_codes))


def test_every_country_default_language_resolves():
    for country in COUNTRIES:
        assert get_language(country.default_language_code) is not None
