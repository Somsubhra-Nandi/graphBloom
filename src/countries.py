"""Static map of common demonyms and country variants to canonical country names.

Used to merge extracted entities ('American', 'USA', 'U.S.' -> 'United States') and, with the same
function, to normalize both sides when matching gold evidence later. England, Scotland and Wales stay
separate entities; 'English' and 'British' map to the United Kingdom.
"""
from src.graph import normalize

_GROUPS = {
    "United States": ["American", "USA", "U.S.", "US", "U.S.A.", "United States of America"],
    "United Kingdom": ["British", "English", "UK", "U.K.", "Great Britain", "Britain"],
    "England": [],
    "Scotland": ["Scottish"],
    "Wales": ["Welsh"],
    "Ireland": ["Irish"],
    "Germany": ["German"],
    "France": ["French"],
    "Italy": ["Italian"],
    "Spain": ["Spanish"],
    "Portugal": ["Portuguese"],
    "Netherlands": ["Dutch", "Holland", "The Netherlands"],
    "Belgium": ["Belgian"],
    "Switzerland": ["Swiss"],
    "Austria": ["Austrian"],
    "Sweden": ["Swedish"],
    "Norway": ["Norwegian"],
    "Denmark": ["Danish"],
    "Finland": ["Finnish"],
    "Poland": ["Polish"],
    "Hungary": ["Hungarian"],
    "Czech Republic": ["Czech", "Czechoslovakia", "Czechoslovak"],
    "Russia": ["Russian"],
    "Soviet Union": ["Soviet", "USSR", "U.S.S.R."],
    "Ukraine": ["Ukrainian"],
    "Romania": ["Romanian"],
    "Bulgaria": ["Bulgarian"],
    "Serbia": ["Serbian"],
    "Croatia": ["Croatian"],
    "Greece": ["Greek"],
    "Turkey": ["Turkish"],
    "Israel": ["Israeli"],
    "Egypt": ["Egyptian"],
    "Iran": ["Iranian"],
    "Lebanon": ["Lebanese"],
    "India": ["Indian"],
    "Pakistan": ["Pakistani"],
    "Bangladesh": ["Bangladeshi"],
    "Sri Lanka": ["Sri Lankan"],
    "China": ["Chinese"],
    "Japan": ["Japanese"],
    "South Korea": ["South Korean", "Korean"],
    "North Korea": ["North Korean"],
    "Hong Kong": [],
    "Taiwan": ["Taiwanese"],
    "Philippines": ["Filipino", "Philippine"],
    "Thailand": ["Thai"],
    "Vietnam": ["Vietnamese"],
    "Indonesia": ["Indonesian"],
    "Australia": ["Australian"],
    "New Zealand": ["New Zealander"],
    "Canada": ["Canadian"],
    "Mexico": ["Mexican"],
    "Brazil": ["Brazilian"],
    "Argentina": ["Argentine", "Argentinian", "Argentinean"],
    "Chile": ["Chilean"],
    "Colombia": ["Colombian"],
    "Peru": ["Peruvian"],
    "Cuba": ["Cuban"],
    "South Africa": ["South African"],
    "Nigeria": ["Nigerian"],
}

CANONICAL = {}  # normalized variant -> canonical name (canonical names map to themselves)
for _canon, _variants in _GROUPS.items():
    for _name in [_canon, *_variants]:
        CANONICAL[normalize(_name)] = _canon


def canonical_country(name):
    """Canonical country name for a country or demonym, else None."""
    return CANONICAL.get(normalize(name))
