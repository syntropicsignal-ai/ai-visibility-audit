"""Curated countries + languages for SERP geo targeting."""

from dataclasses import dataclass
from typing import NewType


CountryCode = NewType("CountryCode", str)
LanguageCode = NewType("LanguageCode", str)


@dataclass(frozen=True, slots=True)
class Country:
    iso_code: CountryCode
    name: str
    default_language_code: LanguageCode
    dfs_location_code: int


@dataclass(frozen=True, slots=True)
class Language:
    code: LanguageCode
    name: str


COUNTRIES: tuple[Country, ...] = (
    Country(CountryCode("US"), "United States", LanguageCode("en"), 2840),
    Country(CountryCode("GB"), "United Kingdom", LanguageCode("en"), 2826),
    Country(CountryCode("CA"), "Canada", LanguageCode("en"), 2124),
    Country(CountryCode("AU"), "Australia", LanguageCode("en"), 2036),
    Country(CountryCode("IE"), "Ireland", LanguageCode("en"), 2372),
    Country(CountryCode("DE"), "Germany", LanguageCode("de"), 2276),
    Country(CountryCode("FR"), "France", LanguageCode("fr"), 2250),
    Country(CountryCode("ES"), "Spain", LanguageCode("es"), 2724),
    Country(CountryCode("IT"), "Italy", LanguageCode("it"), 2380),
    Country(CountryCode("NL"), "Netherlands", LanguageCode("nl"), 2528),
    Country(CountryCode("BE"), "Belgium", LanguageCode("nl"), 2056),
    Country(CountryCode("PL"), "Poland", LanguageCode("pl"), 2616),
    Country(CountryCode("CZ"), "Czech Republic", LanguageCode("cs"), 2203),
    Country(CountryCode("SE"), "Sweden", LanguageCode("sv"), 2752),
    Country(CountryCode("NO"), "Norway", LanguageCode("no"), 2578),
    Country(CountryCode("DK"), "Denmark", LanguageCode("da"), 2208),
    Country(CountryCode("FI"), "Finland", LanguageCode("fi"), 2246),
    Country(CountryCode("PT"), "Portugal", LanguageCode("pt"), 2620),
    Country(CountryCode("BR"), "Brazil", LanguageCode("pt"), 2076),
    Country(CountryCode("MX"), "Mexico", LanguageCode("es"), 2484),
    Country(CountryCode("JP"), "Japan", LanguageCode("ja"), 2392),
    Country(CountryCode("IN"), "India", LanguageCode("en"), 2356),
)

LANGUAGES: tuple[Language, ...] = (
    Language(LanguageCode("en"), "English"),
    Language(LanguageCode("de"), "German"),
    Language(LanguageCode("fr"), "French"),
    Language(LanguageCode("es"), "Spanish"),
    Language(LanguageCode("it"), "Italian"),
    Language(LanguageCode("nl"), "Dutch"),
    Language(LanguageCode("pl"), "Polish"),
    Language(LanguageCode("cs"), "Czech"),
    Language(LanguageCode("sv"), "Swedish"),
    Language(LanguageCode("no"), "Norwegian"),
    Language(LanguageCode("da"), "Danish"),
    Language(LanguageCode("fi"), "Finnish"),
    Language(LanguageCode("pt"), "Portuguese"),
    Language(LanguageCode("ja"), "Japanese"),
)


_COUNTRY_BY_ISO: dict[str, Country] = {c.iso_code: c for c in COUNTRIES}
_LANGUAGE_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}


def get_country(iso_code: CountryCode) -> Country | None:
    return _COUNTRY_BY_ISO.get(iso_code.upper())


def get_language(code: LanguageCode) -> Language | None:
    return _LANGUAGE_BY_CODE.get(code)


DEFAULT_COUNTRY = COUNTRIES[0]
DEFAULT_LANGUAGE = LANGUAGES[0]
