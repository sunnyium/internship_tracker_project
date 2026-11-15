"""Heuristic job extraction from an arbitrary HTML document.

The last-resort path, used when a career page isn't on any platform we
recognize. It works by matching job links on their URL *shape* rather than
their CSS classes, because career sites built on React/Next generate class
names at build time ("css-1x9j2kf") and any class-based selector breaks on the
company's next redeploy. A job detail page's URL almost never changes.

Also lives here: telling a bot wall apart from an empty job list, which matter
for completely different reasons (see BLOCK_SIGNATURES).
"""

import re

from bs4 import BeautifulSoup

from tracker.sources.common import origin as url_origin

# Deliberately loose: a few false positives are harmless (pipeline.py drops
# anything whose title doesn't look like an internship), whereas a missed job
# is a missed job. Override per source with `link_pattern` when a site needs
# something tighter.
JOB_LINK_RE = re.compile(
    # Job id in the path: /jobs/12345, /careers/details/12345, /p/ab12-intern
    r"/(?:jobs?|positions?|openings?|vacanc(?:y|ies)|opportunit(?:y|ies)|careers?|role|p)/[\w./+-]*\d"
    # Job id in the query string: /job?id=R00012345 (Snap), or with an extra
    # path segment before the query like /jobs/JobDetail?jobId=12345 (Booz
    # Allen). Requires a param whose NAME ends in "id" (not just any digit
    # anywhere in the query) - a looser "any digit" version also matched
    # unrelated links like /jobs/intro?hashed=-435680032 (SAS's plain intro
    # page, not a posting).
    r"|/(?:jobs?|positions?|openings?|role)(?:/[\w-]+)*\?(?:[\w%.+-]*&)?\w*[iI][dD]=\w*\d",
    re.I,
)

# Job ids from the heuristic scrape are deliberately NOT tagged with the
# source type. Whether a page was fetched over plain HTTP or rendered in a
# browser is an implementation detail that changes as sites change, and job ids
# are the dedupe key in seen_jobs.db - putting the strategy in the id means
# flipping a source from `auto` to `browser` makes every already-seen posting
# look brand new and re-notifies you for all of it. "auto" rather than
# something tidier because that's what existing databases already contain.
_HEURISTIC_ID_PREFIX = "auto"

# Bot walls / WAF interstitials. Worth telling apart from "the job list didn't
# load", because the two need completely different responses: one is a config
# knob away from working, the other means the site has decided it doesn't want
# automated traffic and the honest answer is to check it by hand.
BLOCK_SIGNATURES = (
    "access denied",
    "you don't have permission to access",
    "errors.edgesuite.net",          # Akamai (what tesla.com serves)
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "request unsuccessful. incapsula",
    "pardon our interruption",       # PerimeterX/HUMAN
    "are you a robot",
    "human verification",            # AWS WAF captcha challenge (what SAS's iCIMS board serves)
    "awswaf.com",
)


def looks_blocked(html):
    """True if a rendered page looks like a bot wall rather than the real site.
    Only consulted once extraction has already come up empty, so a job posting
    that happens to contain one of these phrases can't trip it."""
    head = html[:4000].lower()
    return any(sig in head for sig in BLOCK_SIGNATURES)


def _link_title(el):
    """Best-guess title for a job link.

    A heading *inside* the link first: plenty of boards wrap an entire job
    card in one anchor, where the link text comes back as "Executive Assistant
    New York, NY Full-Time $90,000". Then the link's own text, then
    accessibility attributes, then the nearest preceding heading - which is
    what server-rendered pages like Google's need, but which would hand back a
    section header like "Open roles" for every card in a grid, hence last."""
    inner_heading = el.find(["h1", "h2", "h3", "h4", "h5"]) if el.name else None
    if inner_heading:
        text = inner_heading.get_text(" ", strip=True)
        if text:
            return text

    for candidate in (el.get_text(" ", strip=True), el.get("aria-label"), el.get("title")):
        if candidate:
            candidate = candidate.strip()
            # Long strings mean the "link" wraps a whole card of metadata
            # (location, team, description) rather than just a title.
            if 2 < len(candidate) < 250:
                return candidate
    heading = el.find_previous(["h1", "h2", "h3", "h4"])
    return heading.get_text(" ", strip=True) if heading else ""


def _card_title(card, anchor):
    """Title for a `list_selector` that points at a job card rather than the
    link itself. The card's own text would come back as "Data Analyst Intern
    Austin, TX Apply" - every scrap of metadata in it - so prefer the heading
    inside the card, then the link text, and only fall back to the whole card."""
    heading = card.find(["h1", "h2", "h3", "h4", "h5"])
    if heading:
        text = heading.get_text(" ", strip=True)
        if text:
            return text
    return _link_title(anchor) or _link_title(card)


def extract_jobs_from_html(html, cfg, url):
    """Heuristic job extraction from an HTML document, rendered or not.

    Shared by fetch_browser and fetch_auto's last-resort path. Uses
    `list_selector` if the source provides one, otherwise matches job-shaped
    links (see JOB_LINK_RE). Returns [] rather than raising when it finds
    nothing, so callers can decide whether to try a different strategy."""
    soup = BeautifulSoup(html, "html.parser")
    origin = url_origin(url)
    link_re = re.compile(cfg["link_pattern"], re.I) if cfg.get("link_pattern") else JOB_LINK_RE

    if cfg.get("list_selector"):
        elements = soup.select(cfg["list_selector"])
    else:
        elements = soup.find_all("a", href=link_re)

    jobs = []
    seen_hrefs = set()
    for el in elements:
        # A list_selector may point at a card wrapping the link rather than
        # the link itself - accept either.
        anchor = el if el.name == "a" and el.get("href") else el.find("a", href=True)
        if not anchor:
            continue
        href = anchor["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        full_url = href if href.startswith("http") else origin + "/" + href.lstrip("/")
        if full_url in seen_hrefs:
            continue
        seen_hrefs.add(full_url)

        title = _link_title(anchor) if anchor is el else _card_title(el, anchor)
        if not title:
            continue
        jobs.append({
            # Keyed on the URL: these pages rarely expose a stable internal
            # job id, and the detail-page URL is the next most stable thing.
            "id": f"{_HEURISTIC_ID_PREFIX}:{cfg.get('name', url)}:{href}",
            "title": title,
            "url": full_url,
            "company": cfg.get("name", url),
            "location": "",
            "description": "",
            # No parseable date on a listing page - pipeline.py keeps undated
            # postings rather than dropping what it can't verify the age of.
            "posted_at": None,
        })
    return jobs
