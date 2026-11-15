"""One polling round: fetch every source, decide what's worth telling you
about, send a single digest.

Not an entrypoint - running this file directly fails with "No module named
'tracker'", because Python then puts tracker/ on the import path instead of the
project root. Run `python run.py` from the project root instead.

A posting has to survive five checks to reach you, ordered cheapest-first so
the LLM is only ever asked about the genuinely ambiguous ones:

    1. location filter    outside US/CA, and we're sure -> drop
    2. degree filter      explicitly Masters/PhD-only -> drop
    3. term filter        explicitly Fall/Winter/Spring, no Summer -> drop
    4. title check        doesn't look like an internship at all -> drop
    5. keyword match      hits config.yaml's keywords -> notify
       ...otherwise       ask the LLM classifier, which is biased toward yes

Every one of those fails open. The whole tracker is tuned on the assumption
that a false positive costs one line in an email and a false negative costs an
opportunity.

A round has two stages, and the split is what keeps it both fast and simple:

    fetch      concurrent, many sources at once, no shared state touched
    process    single-threaded - filters, the LLM call, and every database
               write happen here, in companies.yaml order

Notification happens once, after the very last company has been processed -
never per source and never per batch. See _run_once.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from tracker import classifier, notifiers, sources, state
from tracker.filters import degree, location, term
from tracker.sources import rendering

# Fallback when config.yaml doesn't set max_fetch_workers.
DEFAULT_FETCH_WORKERS = 10


def is_recent(job, max_age_hours):
    """True if the job's posted_at is within the allowed window, OR if the
    source didn't give us a date at all (we'd rather show an undated
    posting than silently drop something we can't verify the age of)."""
    posted_at = job.get("posted_at")
    if posted_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    return posted_at >= cutoff


def looks_like_internship(title: str, hints: list[str]) -> bool:
    """Word-boundary match, not substring - "intern" as a plain substring
    matches inside "International" and "Internal", which turned "Internal
    Audit Analyst" and "International Sales Rep" into false positives."""
    t = title.lower()
    return any(re.search(rf"\b{re.escape(h.lower())}\b", t) for h in hints)


def matches_keyword(title: str, description: str, keywords: list[str]) -> bool:
    text = f" {title.lower()} {description.lower()} "
    return any(k.lower() in text for k in keywords)


def process_job(job, cfg, ai_api_key):
    """Returns (should_notify, reason) for a single new job. reason is
    always populated - either why it was flagged relevant, or why it
    wasn't, so callers can log both cases."""
    title = job["title"]
    desc = job.get("description", "")

    loc_cfg = cfg.get("location_filter", {})
    if loc_cfg.get("enabled"):
        allowed, region = location.is_allowed(job.get("location", ""), loc_cfg.get("allowed_regions", ["US", "CA"]))
        if not allowed:
            return False, f"Location filter: '{job.get('location', '')}' classified as {region}, not in allowed regions"

    deg_cfg = cfg.get("degree_filter", {})
    if deg_cfg.get("enabled", True):
        grad_only, deg_reason = degree.is_grad_only(title, desc)
        if grad_only:
            return False, f"Degree filter: {deg_reason}"

    term_cfg = cfg.get("term_filter", {})
    if term_cfg.get("enabled", True):
        wrong_term, term_reason = term.is_wrong_term(
            title, desc, allowed_terms=term_cfg.get("allowed_terms", ["summer"])
        )
        if wrong_term:
            return False, term_reason

    if not looks_like_internship(title, cfg["internship_title_hints"]):
        return False, "Title doesn't look like an internship posting"

    if matches_keyword(title, desc, cfg["keywords"]):
        return True, "Matched keyword filter"

    ai_cfg = cfg.get("ai_classification", {})
    if ai_cfg.get("enabled"):
        relevant, reason = classifier.is_relevant(title, desc, ai_api_key, ai_cfg.get("model", "llama-3.3-70b-versatile"))
        if relevant:
            return True, f"AI double-check: {reason}"
        return False, f"AI double-check: {reason}"

    return False, "No keyword match (AI double-check disabled)"


def run_once(cfg, ai_api_key, notify=True):
    """One sweep of every configured company. Returns the list of
    (job, reason) matches.

    `notify=False` is for run.py, which sweeps the GitHub job-board repos in
    the same round and sends one message covering both rather than one per
    half. Left on by default so any other caller keeps the old behaviour."""
    try:
        return _run_once(cfg, ai_api_key, notify)
    finally:
        # Any headless browser launched this round is reused across sources
        # (launching one per source would cost seconds each), but not held
        # open between rounds - this process is meant to run for weeks.
        sources.close_browser()


def _run_once(cfg, ai_api_key, notify=True):
    # Matches are collected across every source and sent as a single digest at
    # the end of the round, rather than one notification per posting - a sweep
    # of this many companies can turn up a dozen at once.
    matches = []
    try:
        _collect_matches(cfg, ai_api_key, matches)
    finally:
        # In a finally so an unexpected error late in the sweep still gets you
        # the matches found before it. Jobs are marked seen the moment they're
        # examined, so anything not sent here is never offered again.
        if notify:
            notifiers.notify_all(matches, cfg["notifications"])
    return matches


def _fetch_in_parallel(indexed_cfgs, workers):
    """Fetch many sources at once. Returns {index: (jobs, error)}.

    Browser rendering is switched OFF for the duration. Playwright's sync API
    is not thread-safe - driving one shared Chromium from a pool of threads
    corrupts its internal state - so nothing in here is allowed to reach for a
    browser. Sources that needed one come back as errors and get a second,
    sequential pass in _fetch_sources below.
    """
    results = {}
    was_enabled = rendering.BROWSER_OPTIONS.get("enabled", False)
    rendering.BROWSER_OPTIONS["enabled"] = False
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(sources.fetch_all_jobs, c): i for i, c in indexed_cfgs}
            for future in as_completed(pending):
                index = pending[future]
                try:
                    results[index] = (future.result(), None)
                except Exception as e:
                    results[index] = ([], e)
    finally:
        rendering.BROWSER_OPTIONS["enabled"] = was_enabled
    return results


def _fetch_sources(source_cfgs, workers):
    """Fetch every configured source, returning {index: (jobs, error)} keyed by
    position in companies.yaml so results can be reported in config order.

    Two phases, because fetching splits cleanly into "network waiting" (which
    parallelizes perfectly) and "drive a real browser" (which does not):

        1. everything except `type: browser`, concurrently, no rendering
        2. whatever still needs a browser, one at a time

    Phase 2 covers explicit `type: browser` sources plus any `auto` source that
    exhausted its HTTP strategies in phase 1 - those raise rather than return
    empty, which is what distinguishes "needs rendering" from "this company
    genuinely has no openings right now".
    """
    explicit_browser = [i for i, c in enumerate(source_cfgs) if c.get("type") == "browser"]
    parallel = [(i, c) for i, c in enumerate(source_cfgs) if c.get("type") != "browser"]

    print(f"Fetching {len(parallel)} source(s), {workers} at a time...")
    results = _fetch_in_parallel(parallel, workers)

    needs_browser = list(explicit_browser)
    if rendering.browser_enabled():
        # Only `auto` is worth retrying: a Greenhouse slug that 404s won't
        # start working just because we point a browser at it.
        needs_browser += [
            i for i, c in parallel
            if results[i][1] is not None and c.get("type") == "auto"
        ]

    if needs_browser:
        print(f"Rendering {len(needs_browser)} source(s) that need a real browser (~10s each)...")
        for index in needs_browser:
            source_cfg = source_cfgs[index]
            try:
                results[index] = (sources.fetch_all_jobs(source_cfg), None)
            except Exception as e:
                results[index] = ([], e)

    # Anything never attempted (explicit browser sources when rendering is off)
    # still needs an entry so the caller can iterate without checking.
    for index in explicit_browser:
        results.setdefault(index, ([], ValueError(
            "type: browser source skipped - browser rendering is unavailable"
        )))
    return results


def _collect_matches(cfg, ai_api_key, matches):
    """Appends (job, reason) for every new relevant posting to `matches`.
    Takes the list as an argument rather than returning it so a caller can
    still see partial results if this raises partway through.

    Fetching happens up front and concurrently; everything after it - filtering,
    the LLM call, and every write to seen_jobs.db - runs single-threaded here.
    That split is deliberate: SQLite connections and the notification digest
    stay in one thread, so no locking is needed anywhere.
    """
    max_age_hours = cfg.get("max_posting_age_hours", 24)
    source_cfgs = cfg["sources"]
    workers = max(1, int(cfg.get("max_fetch_workers", DEFAULT_FETCH_WORKERS)))
    verbose = bool(cfg.get("verbose_logging", False))

    fetched = _fetch_sources(source_cfgs, workers)

    # Read the whole dedupe state once rather than querying per posting. With a
    # seven-day window a round can examine tens of thousands of postings, and
    # nearly all of them are already known.
    seen_ids = state.all_seen_ids()
    baselined = state.baselined_sources()

    for index, source_cfg in enumerate(source_cfgs):
        name = source_cfg.get("name", source_cfg["type"])
        jobs, error = fetched[index]
        if error is not None:
            print(f"[{name}] Fetch failed, skipping this round: {error}")
            continue

        jobs = [j for j in jobs if is_recent(j, max_age_hours)]

        # First time we've successfully reached this source: everything it
        # currently lists is "pre-existing", not new. Record it as seen
        # without notifying, so only postings that appear after this point
        # ever trigger an alert.
        if name not in baselined:
            state.mark_seen_many(
                (job["id"], name, job["title"], job["url"]) for job in jobs
            )
            seen_ids.update(job["id"] for job in jobs)
            state.mark_baselined(name)
            baselined.add(name)
            print(f"[{name}] First check - recorded {len(jobs)} existing posting(s) as baseline, won't notify for these.")
            continue

        new_count = 0
        match_count = 0
        for job in jobs:
            if job["id"] in seen_ids:
                continue
            # Mark seen immediately so a crash mid-loop can't cause repeat spam
            state.mark_seen(job["id"], name, job["title"], job["url"])
            seen_ids.add(job["id"])
            new_count += 1

            try:
                should_notify, reason = process_job(job, cfg, ai_api_key)
            except Exception as e:
                print(f"[{name}] Error classifying '{job['title']}': {e}")
                continue

            if should_notify:
                matches.append((job, reason))
                match_count += 1
                print(f"[{name}] MATCH: {job['title']} -> {job['url']}")
            elif verbose:
                print(f"[{name}] Not relevant: {job['title']} ({reason}) -> {job['url']}")

        # One line per source instead of one per rejected posting. Unattended
        # runs append to a log file nobody reads until something looks wrong,
        # and a seven-day window across 268 companies makes the per-posting
        # version tens of thousands of lines per round. Rejections are still
        # available by turning verbose_logging on in config.yaml.
        if new_count:
            print(f"[{name}] {len(jobs)} posting(s) in window, {new_count} new, {match_count} relevant")


def print_job_counts():
    """Prints total jobs ever seen per source (baseline + new, cumulative
    across all runs)."""
    counts = state.count_by_source()
    if not counts:
        print("No jobs recorded yet.")
        return
    print("Total jobs seen per company:")
    for source_name, count in counts:
        print(f"  {source_name}: {count}")
