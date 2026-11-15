"""
Headless-browser rendering for JavaScript-rendered career pages.

Some career sites (Tesla, Meta, TikTok, Snap, ...) ship almost no HTML - the
job list is drawn by JavaScript after the page loads, so `requests` +
BeautifulSoup see an empty shell no matter how good a CSS selector you give
them. This module drives a real headless Chromium via Playwright, lets the
page's JavaScript run, and hands back the *rendered* HTML so the extraction
path in sources/extract.py has something to actually parse.

Two layers, in this order below:

    the driver      is_available / render / shutdown - talks to Playwright
    the settings    configure_browser / render_options - resolves config.yaml's
                    `browser_rendering` block against per-source overrides

Playwright is an OPTIONAL dependency. If it isn't installed, is_available()
returns False and the rest of the tracker keeps working exactly as before on
plain-HTTP sources - nothing here is imported at module load time. To enable:

    pip install playwright
    playwright install chromium      # one-time ~150MB browser download

The Chromium process is launched lazily on first use and reused for every
source in a polling round, since launching one per source would add about a
second each across dozens of sources. shutdown() closes it at the end of the
round, so a tracker left running for weeks isn't holding a browser open the
entire time.
"""

import atexit

# A realistic desktop user-agent matters here in a way it doesn't for the
# JSON APIs: career sites that bother with client-side rendering also tend to
# serve a degraded page (or a bot wall) to anything that self-identifies as a
# script, which would defeat the point of rendering at all.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT_MS = 30000
# Job lists commonly arrive in a second request fired after the framework
# mounts, which "networkidle" can miss - this is a small unconditional grace
# period on top of it. 2500ms was measurably too tight (Atlassian's list
# raced it); 4000 held up across every site tested.
DEFAULT_WAIT_AFTER_LOAD_MS = 4000

# How the job-list wait decides it's done: the matching link (or card) count is
# above zero and unchanged for STABLE_POLLS checks in a row, POLL_MS apart.
POLL_MS = 500
STABLE_POLLS = 3

# Nothing the scraper reads is in these, and on a media-heavy careers page they
# are most of the bytes.
BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}

_COUNT_LINKS_JS = """([pattern, selector]) => {
    if (selector) return document.querySelectorAll(selector).length;
    const re = new RegExp(pattern, "i");
    let n = 0;
    for (const a of document.querySelectorAll("a[href]")) {
        if (re.test(a.getAttribute("href"))) n++;
    }
    return n;
}"""

_playwright = None
_browser = None


def is_available() -> bool:
    """True if Playwright is importable. Doesn't check whether the Chromium
    binary itself was downloaded (`playwright install chromium`) - that
    failure surfaces as a clear error from render() instead."""
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _get_browser():
    global _playwright, _browser
    if _browser is not None:
        return _browser
    from playwright.sync_api import sync_playwright

    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(
        headless=True,
        # Hides the most obvious "this is automated" signal. Not an attempt to
        # defeat bot detection - just avoids sites serving a degraded page.
        args=["--disable-blink-features=AutomationControlled"],
    )
    atexit.register(shutdown)
    return _browser


def shutdown():
    """Close the shared browser. Safe to call when nothing was ever launched,
    and safe to call repeatedly - the next render() relaunches on demand."""
    global _playwright, _browser
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass  # already dead / crashed - nothing useful to do here
        _browser = None
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None


def _wait_for_job_links(page, link_pattern, list_selector, timeout_ms):
    """Poll until the job list has arrived and stopped growing. True if it
    settled, False if the timeout ran out first (the caller then parses
    whatever is there, as before)."""
    if not link_pattern and not list_selector:
        from tracker.sources.extract import JOB_LINK_RE
        link_pattern = JOB_LINK_RE.pattern
    last, steady, waited = -1, 0, 0
    while waited < timeout_ms:
        try:
            count = page.evaluate(_COUNT_LINKS_JS, [link_pattern or "", list_selector or ""])
        except Exception:
            count = 0  # mid-navigation; try again on the next poll
        if count and count == last:
            steady += 1
            if steady >= STABLE_POLLS:
                return True
        else:
            steady = 0
        last = count
        page.wait_for_timeout(POLL_MS)
        waited += POLL_MS
    return False


def render(
    url,
    wait_for_selector=None,
    wait_after_load_ms=DEFAULT_WAIT_AFTER_LOAD_MS,
    timeout_ms=DEFAULT_TIMEOUT_MS,
    scroll_times=0,
    click_selector=None,
    max_clicks=0,
    link_pattern=None,
    list_selector=None,
    grace_is_explicit=False,
):
    """Load `url` in headless Chromium and return the rendered HTML.

    wait_for_selector  CSS selector to wait for before reading the page (the
                       most reliable signal that the job list has arrived).
                       If not set, waits until job-shaped links (link_pattern,
                       or the default JOB_LINK_RE) - or list_selector cards -
                       have appeared and stopped multiplying. That replaced
                       waiting for network idle, which analytics-heavy sites
                       never reach, so it cost the full timeout every round.
    wait_after_load_ms extra grace period after the wait above. Skipped after
                       the job-link wait succeeds, unless the source sets it
                       itself (grace_is_explicit).
    scroll_times       scroll to the bottom this many times, for career pages
                       that lazy-load more jobs as you scroll.
    click_selector     selector for a "Load more" / "Show more jobs" button.
    max_clicks         how many times to click it (stops early once the button
                       disappears or stops being clickable).

    Every wait is best-effort: on timeout it extracts whatever *did* render
    rather than raising, since a partial job list beats no job list.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    browser = _get_browser()
    context = browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="en-US",
    )
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES
        else route.continue_(),
    )
    page = context.new_page()
    try:
        # "domcontentloaded" rather than "load": on these sites the load event
        # often waits on analytics/ad requests that have nothing to do with
        # the job list, and the explicit waits below are the real signal.
        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

        links_settled = False
        try:
            if wait_for_selector:
                page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            else:
                links_settled = _wait_for_job_links(page, link_pattern, list_selector, timeout_ms)
        except PlaywrightTimeoutError:
            pass  # best-effort: parse whatever rendered

        if wait_after_load_ms and (grace_is_explicit or not links_settled):
            page.wait_for_timeout(wait_after_load_ms)

        for _ in range(scroll_times):
            page.mouse.wheel(0, 20000)
            page.wait_for_timeout(1200)

        if click_selector:
            for _ in range(max_clicks):
                try:
                    button = page.locator(click_selector).first
                    if not button.is_visible(timeout=2000):
                        break
                    button.click(timeout=5000)
                    page.wait_for_timeout(1500)
                except Exception:
                    # Button gone, detached, or covered - we've loaded as much
                    # as we're going to. Keep what we have.
                    break

        return page.content()
    finally:
        try:
            page.close()
            context.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Settings layer
# ---------------------------------------------------------------------------

# Set from config.yaml's `browser_rendering` block at startup (see
# tracker/config.py). Kept as module state rather than threaded through every
# fetch_* signature because it's a single global switch, not per-source
# behavior - individual sources can still override any of these keys in
# config/companies.yaml.
BROWSER_OPTIONS = {"enabled": False}

# Render options a source may override individually in config/companies.yaml.
_RENDER_KEYS = (
    "wait_for_selector", "wait_after_load_ms", "timeout_ms",
    "scroll_times", "click_selector", "max_clicks",
)


def configure_browser(opts):
    """Apply config.yaml's `browser_rendering` settings. Called once at
    startup; with no call at all, browser rendering stays off and every source
    behaves as if this module didn't exist."""
    BROWSER_OPTIONS.update(opts or {})


def close_browser():
    """Release the shared Chromium process. Called at the end of each polling
    round, so a tracker left running for weeks isn't holding a browser open."""
    shutdown()


def render_options(cfg):
    """Per-source overrides layered on top of the global browser settings.
    Also passes the source's own link_pattern / list_selector, which tell the
    job-list wait what to count."""
    opts = {}
    for key in _RENDER_KEYS:
        if key in cfg:
            opts[key] = cfg[key]
        elif key in BROWSER_OPTIONS:
            opts[key] = BROWSER_OPTIONS[key]
    for key in ("link_pattern", "list_selector"):
        if cfg.get(key):
            opts[key] = cfg[key]
    opts["grace_is_explicit"] = "wait_after_load_ms" in cfg
    return opts


def browser_enabled():
    """True when `auto` sources are allowed to fall back to rendering. An
    explicit `type: browser` source renders regardless of this."""
    return bool(BROWSER_OPTIONS.get("enabled")) and is_available()
