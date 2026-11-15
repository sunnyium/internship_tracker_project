"""Cross-source duplicate detection for one round's digest.

    Entry              | one match, tagged with where it came from
    split_duplicates() | (first sightings, repeats) in the order given
    format_duplicates()| the "Duplicates" block that closes a digest

Roughly fifty GitHub lists and eleven hundred career pages overlap heavily by
design: the same Greenhouse posting is scraped from the company's own site,
crowdsourced into Simplify, mirrored into three smaller lists and rewritten by
jobright behind a tracking URL. Notifying five times for one job is what makes
a digest unreadable.

The first sighting wins and everything after it moves to the bottom of the
message, which is why the entries handed in here have to arrive in the order
they should be kept - career pages before GitHub lists, since a company's own
posting is the more authoritative link.

Two keys decide sameness, and both are needed:

    url    the same posting reached by the same link, ignoring the tracking
           parameters jobright and the badge generators bolt on
    text   company, title and location, for the aggregators that wrap every
           link in a redirect of their own and so can never match on URL

Location is part of the text key on purpose. "Software Engineer Intern" at
TikTok in San Jose and the same title in Seattle are two applications, not one
posting listed twice.
"""

import re
from collections import namedtuple

from github_boards.normalize import canonical_url

# section: which half of the digest this belongs under
# source:  the company or repo that surfaced it, named in the duplicates block
Entry = namedtuple("Entry", "section source job reason")

PUNCTUATION = re.compile(r"[^a-z0-9]+")


def _text_key(job):
    parts = (job.get("company", ""), job.get("title", ""), job.get("location", ""))
    return "|".join(PUNCTUATION.sub(" ", p.lower()).strip() for p in parts)


def _keys(job):
    """Every key this posting should be recognized by. A URL-less row still
    gets a text key, so it is never treated as unique by default."""
    keys = []
    url = canonical_url(job.get("url", ""))
    if url:
        keys.append(f"url:{url}")
    text = _text_key(job)
    if text.strip("| "):
        keys.append(f"text:{text}")
    return keys


def split_duplicates(entries):
    """(unique, duplicates) where duplicates is [(repeat, first_seen)].

    Order is preserved: `unique` keeps the first sighting of each posting in
    the order handed in, and `duplicates` keeps the repeats in the order they
    were found, each paired with the entry it duplicates."""
    first_by_key = {}
    unique = []
    duplicates = []
    for entry in entries:
        keys = _keys(entry.job)
        match = next((first_by_key[k] for k in keys if k in first_by_key), None)
        if match is not None:
            duplicates.append((entry, match))
            continue
        for key in keys:
            first_by_key[key] = entry
        unique.append(entry)
    return unique, duplicates


def format_duplicates(duplicates):
    """The block listing every repeat and where its kept copy is.

    Each line names both sources, because "this also showed up in the Canadian
    list" is the useful part - it says which of the fifty lists is actually
    earning its place."""
    lines = []
    for repeat, first in duplicates:
        job = repeat.job
        lines.append(
            f"{job.get('title', '')} - {job.get('company') or 'unknown'}\n"
            f"Also listed by: {repeat.source or repeat.section}\n"
            f"Already shown under: {first.section} / {first.source or 'unknown'}\n"
            f"Link: {job.get('url', '')}"
        )
    return "\n\n".join(lines)
