"""Fetchers for career pages that aren't on a platform we have an API for.

    generic_html   a plain HTTP scrape driven by an explicit `list_selector`
    browser        render in headless Chromium, then extract heuristically
    auto           try everything, cheapest first - the type most sources use

`auto` is the interesting one and the reason config/companies.yaml is mostly
one-liners. It escalates through four strategies and only pays for the
expensive ones when the cheap ones come up empty.
"""

import requests
from bs4 import BeautifulSoup

from tracker.sources import detect, rendering
from tracker.sources.common import HEADERS, TIMEOUT, host as url_host
from tracker.sources.extract import extract_jobs_from_html, looks_blocked


def fetch_generic_html(cfg):
    url = cfg["url"]
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    elements = soup.select(cfg["list_selector"])
    base_url = cfg.get("base_url", "")
    link_attr = cfg.get("link_attr", "href")
    jobs = []
    for el in elements:
        title = el.get_text(" ", strip=True)
        href = el.get(link_attr, "")
        if href and not href.startswith("http"):
            href = base_url.rstrip("/") + "/" + href.lstrip("/")
        if not title or not href:
            continue
        job_id = f"generic:{cfg['name']}:{href}"
        jobs.append({
            "id": job_id,
            "title": title,
            "url": href,
            "company": cfg.get("name", url),
            "location": "",
            "description": "",
            # Static HTML pages generally don't expose a parseable posting
            # date - left as None (pipeline.py won't drop it, since we can't
            # verify it's actually old rather than just undated).
            "posted_at": None,
        })
    return jobs


def fetch_browser(cfg):
    """For career pages whose job list is drawn by JavaScript - a plain HTTP
    response for these contains an empty app shell and nothing else. Renders
    the page in headless Chromium (see rendering.py), then runs the same
    heuristic link extraction against the resulting DOM.

    Use this type when you already know a site needs rendering; `auto` will
    also fall back to it automatically when its cheaper strategies come up
    empty. Options (all optional): wait_for_selector, wait_after_load_ms,
    timeout_ms, scroll_times, click_selector + max_clicks, and
    list_selector / link_pattern to control extraction."""
    if not rendering.is_available():
        raise ValueError(
            "type: browser needs Playwright, which isn't installed. Run "
            "'pip install playwright' then 'playwright install chromium'."
        )
    url = cfg["url"]
    html = rendering.render(url, **rendering.render_options(cfg))

    # Rendering may have exposed a real ATS the raw HTML never mentioned - its
    # API gives us locations and posting dates, which DOM scraping can't.
    detected = detect.sniff_platform(html, url_host(url), url, cfg)
    if detected:
        fetcher, built_cfg = detected
        try:
            jobs = fetcher(built_cfg)
            if jobs:
                return jobs
        except Exception:
            # The detected platform's API is the nicer answer (it carries
            # locations and dates) but it is not the last word - a site can
            # advertise Eightfold/Phenom and still refuse the API call. Fall
            # through to scraping the DOM we already have in hand.
            pass

    # Checked regardless of whether extraction found anything: some WAF
    # challenges (SAS's iCIMS board) run a non-interactive JS proof-of-work
    # that headless Chromium sometimes passes and sometimes doesn't, and on a
    # failed pass the block page can still contain a stray UI link ("Search
    # Jobs") that looks job-shaped. A source that's blocked half the time
    # should error every time, not intermittently report one fake posting.
    if looks_blocked(html):
        raise ValueError(
            f"{url} served a bot-block page instead of the site (see BLOCK_SIGNATURES). "
            "This isn't a config problem and no setting here will fix it - the site is "
            "refusing automated access on purpose. Check this company manually."
        )

    jobs = extract_jobs_from_html(html, cfg, url)
    if not jobs:
        raise ValueError(
            f"Rendered {url} in a browser but found no job-shaped links. Either the job "
            "list needs more time or interaction to appear (try wait_for_selector, "
            "scroll_times, or click_selector + max_clicks), or its links don't match the "
            "default URL pattern (set link_pattern, or list_selector, for this source)."
        )
    return jobs


def fetch_auto(cfg):
    """Best-effort auto-detection: given just a URL, tries (in order) known
    URL patterns, then content signatures, then a generic heuristic HTML
    scrape, and finally - if browser rendering is enabled in config.yaml -
    the same two content strategies again against a browser-rendered DOM.

    That last step is what makes fully JavaScript-rendered sites work. It's
    ordered last on purpose: rendering a page costs seconds and a Chromium
    process, versus milliseconds for a plain request, so it only runs for
    sources that genuinely need it."""
    url = cfg["url"]
    first_error = None

    # Each stage falls through on failure instead of giving up. Detecting a
    # platform is a guess, not a fact: a Phenom site whose ref_num can't be
    # discovered, or an Eightfold instance serving its API from another host,
    # would otherwise abort the whole source and never reach the browser
    # fallback that would have worked.
    for detector in (detect.detect_from_url, detect.sniff_from_content):
        detected = detector(url, cfg)
        if not detected:
            continue
        fetcher, built_cfg = detected
        try:
            jobs = fetcher(built_cfg)
        except Exception as e:
            first_error = first_error or f"{fetcher.__name__} failed: {e}"
            continue
        if jobs:
            return jobs
        first_error = first_error or f"{fetcher.__name__} returned no jobs"

    # Generic heuristic scrape, same approach as fetch_google - match job
    # links by URL shape rather than fragile CSS classes.
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        jobs = extract_jobs_from_html(r.text, cfg, url)
    except requests.exceptions.RequestException:
        # A 403 here is itself a hint that the site expects a real browser.
        jobs = []
    if jobs:
        return jobs

    if rendering.browser_enabled():
        try:
            return fetch_browser(cfg)
        except Exception as e:
            # Surface the earlier platform-specific error too - "Eightfold API
            # rejected this host" is far more actionable than "rendering found
            # no links", and the platform path is the one worth fixing.
            raise ValueError(f"{e}{f' (earlier: {first_error})' if first_error else ''}")

    if rendering.is_available():
        hint = (
            "This site looks fully JavaScript-rendered. Set browser_rendering.enabled: true "
            "in config/config.yaml (or give this source type: browser) to render it in a "
            "real browser."
        )
    else:
        hint = (
            "This site looks fully JavaScript-rendered, which needs a real browser: run "
            "'pip install playwright' and 'playwright install chromium', then set "
            "browser_rendering.enabled: true in config/config.yaml."
        )
    raise ValueError(f"Auto-detection found no known platform and no job-shaped links for {url}. {hint}")
