"""
Term/season filter: excludes postings explicitly naming a cycle Sunny isn't
targeting - a season other than Summer, or a year other than the allowed ones
(2027 and 2028) - and keeps everything else.

Design principles (matching the tracker's overall fail-open philosophy):
- Only exclude when a season is EXPLICITLY named and none of the seasons
  found are in `allowed_terms`. No season mentioned anywhere -> KEEP.
- A posting naming several seasons ("Summer/Fall 2027 Co-op") is kept if any
  one of them is allowed - a multi-cycle role is still open to Sunny.
- In free text (a title or description), a bare season word only counts when
  it sits next to a year. "Fall" and "Winter" are common place-name
  fragments - Fall River MA, Winter Park FL - and without the year anchor
  this filter would drop real postings over their office location. A
  structured term field (Simplify's `terms` list, a markdown table's Term
  column) carries no such risk and is trusted on a bare season word.
"""

import re

SEASON_ALIASES = {
    "spring": "spring", "summer": "summer",
    "fall": "fall", "autumn": "fall",
    "winter": "winter",
}

_SEASON = r"(?:spring|summer|fall|autumn|winter)"
# One or more season words chained by a slash/comma/ampersand, so "Summer/
# Fall 2027" reads as both seasons rather than losing "summer" because it
# isn't the word immediately touching the year.
_SEASON_CHAIN = rf"({_SEASON}(?:\s*[/,&]\s*{_SEASON})*)"
_YEAR = r"(20\d{2})"

# A season chain next to a year, either order: "Fall 2027", "2027 Fall
# cohort", "Summer/Fall 2027".
SEASON_YEAR_PATTERN = re.compile(
    rf"\b{_SEASON_CHAIN}\b[\s,'/-]{{0,4}}{_YEAR}\b|\b{_YEAR}\b[\s,'/-]{{0,4}}{_SEASON_CHAIN}\b",
    re.IGNORECASE,
)
BARE_SEASON_PATTERN = re.compile(rf"\b{_SEASON}\b", re.IGNORECASE)

# Splits a matched chain/word into individual season tokens; also runs over
# a year group harmlessly, since digits never appear in SEASON_ALIASES.
_TOKEN_SPLIT = re.compile(r"[^a-z]+")


def _seasons_in(text, structured):
    """Every season named in `text`, normalized ("autumn" -> "fall")."""
    if not text:
        return set()
    pattern = BARE_SEASON_PATTERN if structured else SEASON_YEAR_PATTERN
    found = set()
    for match in pattern.finditer(text):
        groups = match.groups() if match.groups() else (match.group(0),)
        for group in groups:
            if not group:
                continue
            for token in _TOKEN_SPLIT.split(group.lower()):
                if token in SEASON_ALIASES:
                    found.add(SEASON_ALIASES[token])
    return found


# A bare year in a title or a structured term field ("2026 Start", "Intern
# 2026"). Not applied to descriptions, where copyright lines and founding dates
# would trip it.
BARE_YEAR_PATTERN = re.compile(r"(?<![\w/-])(20\d{2})(?![\w/-])")


def _season_year_pairs(text):
    """{(season, year)} for every season-next-to-year mention in `text`."""
    pairs = set()
    for match in SEASON_YEAR_PATTERN.finditer(text or ""):
        chain_a, year_a, year_b, chain_b = match.groups()
        chain, year = (chain_a, year_a) if chain_a else (chain_b, year_b)
        for token in _TOKEN_SPLIT.split(chain.lower()):
            if token in SEASON_ALIASES:
                pairs.add((SEASON_ALIASES[token], int(year)))
    return pairs


def is_wrong_term(title, description="", term_field="", allowed_terms=("summer",), allowed_years=()):
    """Returns (wrong_term: bool, reason: str). True means the posting
    explicitly targets a cycle outside `allowed_terms` (and, when
    `allowed_years` is given, outside those years) and should be excluded.

    Seasons: a posting naming no season is kept; one naming several is kept
    if any is allowed.

    Years: when a season is named next to a year ("Summer 2026"), at least
    one such pair must be an allowed season in an allowed year. Otherwise a
    bare year in the title or term field ("2026 Start", "Intern 2026") must
    include an allowed year. No year anywhere -> kept."""
    allowed = {t.lower() for t in allowed_terms}
    found = _seasons_in(term_field, structured=True)
    found |= _seasons_in(title, structured=False)
    found |= _seasons_in(description, structured=False)

    if found and not found & allowed:
        return True, f"Term filter: names {'/'.join(sorted(found))}, not {'/'.join(sorted(allowed))}"

    years = {int(y) for y in allowed_years}
    if not years:
        return False, ""

    pairs = _season_year_pairs(title) | _season_year_pairs(term_field) | _season_year_pairs(description)
    if pairs:
        if any(season in allowed and year in years for season, year in pairs):
            return False, ""
        named = ", ".join(f"{s.title()} {y}" for s, y in sorted(pairs, key=lambda p: (p[1], p[0])))
        return True, f"Term filter: names {named}, not {'/'.join(sorted(allowed))} {'/'.join(map(str, sorted(years)))}"

    bare = {int(y) for y in BARE_YEAR_PATTERN.findall(f"{title} {term_field}")}
    if bare and not bare & years:
        return True, f"Term filter: names {'/'.join(map(str, sorted(bare)))}, not {'/'.join(map(str, sorted(years)))}"
    return False, ""
