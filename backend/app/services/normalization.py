"""Canonical values used by incident filters and analytics.

The database stores controlled values without accents for districts and categories,
while people and language models naturally use accents, plurals and local synonyms.
Keeping this mapping in the domain layer prevents each consumer from implementing a
slightly different interpretation of the same filter.
"""

from __future__ import annotations

import unicodedata


def fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold().strip())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


_DISTRICT_ALIASES = {
    "san joaquin": "San Joaquin",
    "san joaquin de flores": "San Joaquin",
    "barrantes": "Barrantes",
    "llorente": "Llorente",
}

_CATEGORY_ALIASES = {
    "ruido": "ruido",
    "ruidos": "ruido",
    "bulla": "ruido",
    "escandalo": "ruido",
    "escandalos": "ruido",
    "robo": "robo",
    "robos": "robo",
    "hurto": "robo",
    "hurtos": "robo",
    "asalto": "robo",
    "asaltos": "robo",
    "pelea": "violencia",
    "peleas": "violencia",
    "violencia": "violencia",
    "violencias": "violencia",
}


def canonical_district(value: str | None) -> str | None:
    if not value:
        return None
    folded = fold_text(value)
    return _DISTRICT_ALIASES.get(folded, value.strip())


def canonical_category(value: str | None) -> str | None:
    if not value:
        return None
    folded = fold_text(value).replace(" ", "_")
    return _CATEGORY_ALIASES.get(folded, value.strip())


def filter_values(value: str | None, *, kind: str) -> tuple[str, ...] | None:
    """Return stored variants for an equality filter, or None when no filter exists."""
    if not value:
        return None
    canonical = canonical_district(value) if kind == "district" else canonical_category(value)
    if kind == "district":
        aliases = {
            "San Joaquin": ("San Joaquin", "San Joaquín", "san joaquin"),
            "Barrantes": ("Barrantes", "barrantes"),
            "Llorente": ("Llorente", "llorente"),
        }
    else:
        aliases = {
            "ruido": ("ruido", "ruidos"),
            "robo": ("robo", "robos", "hurto", "hurtos", "asalto", "asaltos"),
            "violencia": ("violencia", "pelea", "peleas"),
        }
    return aliases.get(canonical, (value.strip(),))

