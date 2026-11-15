"""
Term/season filter: excludes postings explicitly naming a cycle Sunny isn't
targeting (Fall, Winter, Spring), keeps everything else.

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


def is_wrong_term(title, description="", term_field="", allowed_terms=("summer",)):
    """Returns (wrong_term: bool, reason: str). True means the posting
    explicitly targets a cycle outside `allowed_terms` and should be
    excluded. Nothing identifiable, or an allowed season among what's
    named, returns False (keep) - fail-open, same as every filter here."""
    allowed = {t.lower() for t in allowed_terms}
    found = _seasons_in(term_field, structured=True)
    found |= _seasons_in(title, structured=False)
    found |= _seasons_in(description, structured=False)

    if not found or found & allowed:
        return False, ""
    return True, f"Term filter: names {'/'.join(sorted(found))}, not {'/'.join(sorted(allowed))}"
