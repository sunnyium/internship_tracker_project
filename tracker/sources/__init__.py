"""Job source scrapers, one per career-page platform.

Every fetch_* function takes a source config dict from config/companies.yaml
and returns a list of dicts with a consistent shape:

    {
        "id": str,                    # globally unique, stable across runs
        "title": str,
        "url": str,
        "company": str,
        "location": str,
        "description": str,           # plain text, ok if truncated/partial
        "posted_at": datetime | None, # UTC, when the platform provides it
    }

`posted_at` is None wherever the platform doesn't publish one - scraped HTML
listings mostly don't. pipeline.py treats an unknown date as "keep it" rather
than silently dropping a posting it can't verify the age of.

Where the code lives:

    common.py       HTTP settings, date parsers, URL helpers
    boards.py       Greenhouse, Lever, Ashby, Workday - real JSON APIs
    enterprise.py   Apple, Amazon, Google, Oracle, Eightfold, Phenom
    extract.py      heuristic "find the job links" scrape of arbitrary HTML
    detect.py       working out which platform a URL is actually on
    generic.py      generic_html, browser, and the `auto` escalation chain
    rendering.py    headless Chromium, for pages drawn by JavaScript

Adding a platform means writing a fetch_* function in the right module and
adding one line to FETCHERS below.
"""

from tracker.sources import boards, enterprise, generic
from tracker.sources.rendering import close_browser, configure_browser

FETCHERS = {
    # Standard applicant-tracking systems, all with real JSON APIs
    "greenhouse": boards.fetch_greenhouse,
    "lever": boards.fetch_lever,
    "ashby": boards.fetch_ashby,
    "workday": boards.fetch_workday,
    # Large employers with bespoke endpoints
    "apple": enterprise.fetch_apple,
    "amazon": enterprise.fetch_amazon,
    "google": enterprise.fetch_google,
    "oracle_cloud": enterprise.fetch_oracle_cloud,
    "eightfold": enterprise.fetch_eightfold,
    "phenom": enterprise.fetch_phenom,
    # Everything else
    "generic_html": generic.fetch_generic_html,
    "browser": generic.fetch_browser,
    "auto": generic.fetch_auto,
}

__all__ = ["FETCHERS", "fetch_all_jobs", "configure_browser", "close_browser"]


def fetch_all_jobs(source_cfg):
    """Fetch jobs for a single source config dict. Raises on failure -
    caller should catch so one broken source doesn't kill the whole run."""
    fetcher = FETCHERS.get(source_cfg["type"])
    if not fetcher:
        raise ValueError(f"Unknown source type: {source_cfg['type']}")
    return fetcher(source_cfg)
