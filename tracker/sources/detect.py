"""Working out which platform a career page is actually built on.

This is what makes `type: auto` in config/companies.yaml possible - give it a
URL and it finds the right fetcher, so most companies need one line of config
instead of a hand-identified platform and its per-platform keys.

Three strategies, cheapest first:

    detect_from_url       pure string matching on the URL, no network call
    sniff_from_content    fetch the page once, look for platform signatures
    sniff_platform        the same signature check, exposed separately so it
                          can run again against a browser-rendered DOM

That last one matters more than it sounds: plenty of companies bolt a
Greenhouse or Lever board onto their own careers page with JavaScript, so the
raw HTTP response never mentions the ATS and the rendered DOM does.
"""

import re

import requests

from tracker.sources import boards, enterprise
from tracker.sources.common import HEADERS, TIMEOUT, host as url_host

# Client-side-injected job widgets, matched against page text.
GREENHOUSE_SLUG_RE = re.compile(
    # Covers the board URL itself (boards.greenhouse.io/acme,
    # job-boards.greenhouse.io/acme), the API form (v1/boards/acme), and the
    # embed script, whose real shape is .../embed/job_board/js?for=acme
    r"(?:job-)?boards(?:-api)?\.greenhouse\.io/"
    r"(?:embed/job_board(?:/js)?\?for=|v1/boards/)?([a-z0-9_-]+)",
    re.I,
)
LEVER_SLUG_RE = re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I)
# Path segments the patterns above can capture when a page mentions a bare
# board URL with no slug in it.
_NOT_SLUGS = {"embed", "v1", "boards", "job_board", "js", "www"}


def detect_from_url(url, cfg):
    """Recognize a platform purely from the URL shape - no network call
    needed. Returns (fetcher_fn, built_cfg) or None if nothing matches."""
    parsed_host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    path_parts = [p for p in re.sub(r"^https?://[^/]+", "", url).split("?")[0].split("/") if p]

    if "greenhouse.io" in parsed_host and path_parts:
        slug = path_parts[0] if path_parts[0] != "embed" else (path_parts[1] if len(path_parts) > 1 else None)
        if slug:
            return boards.fetch_greenhouse, {**cfg, "slug": slug}

    if "lever.co" in parsed_host and path_parts:
        return boards.fetch_lever, {**cfg, "slug": path_parts[0]}

    if "ashbyhq.com" in parsed_host and path_parts:
        return boards.fetch_ashby, {**cfg, "slug": path_parts[0]}

    if "myworkdayjobs.com" in parsed_host:
        host_parts = parsed_host.split(".")
        if len(host_parts) >= 4 and path_parts:
            tenant, wd_host = host_parts[0], host_parts[1]
            site = path_parts[0]
            return boards.fetch_workday, {**cfg, "tenant": tenant, "host": wd_host, "site": site}

    if parsed_host == "jobs.apple.com":
        return enterprise.fetch_apple, {**cfg}

    return None


def sniff_platform(text, final_host, url, cfg):
    """Look for platform signatures in a page's HTML. Returns
    (fetcher_fn, built_cfg) or None if nothing is recognized.

    Split out from the fetching so it can run twice against the same page:
    once on the raw HTTP response, and again on the browser-rendered DOM,
    which is where client-side-injected job boards finally show up."""
    if "phenompeople.com" in text:
        return enterprise.fetch_phenom, {**cfg, "domain": final_host}

    if "oraclecloud.com" in final_host or re.search(r"siteNumber['\"]?\s*[:=]\s*['\"]CX_\d+", text):
        return enterprise.fetch_oracle_cloud, {**cfg, "careers_url": url}

    if "eightfold.ai" in text or "/api/apply/v2/jobs" in text:
        return enterprise.fetch_eightfold, {**cfg, "careers_url": url}

    match = GREENHOUSE_SLUG_RE.search(text)
    if match and match.group(1).lower() not in _NOT_SLUGS:
        return boards.fetch_greenhouse, {**cfg, "slug": match.group(1)}

    match = LEVER_SLUG_RE.search(text)
    if match and match.group(1).lower() not in _NOT_SLUGS:
        return boards.fetch_lever, {**cfg, "slug": match.group(1)}

    return None


def sniff_from_content(url, cfg):
    """Fetch the page once and sniff it for platform signatures. Returns
    (fetcher_fn, built_cfg) or None if nothing is recognized - callers should
    fall back to the generic heuristic scrape."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except requests.exceptions.RequestException:
        return None

    return sniff_platform(r.text, url_host(r.url), url, cfg)
