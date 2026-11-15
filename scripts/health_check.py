"""
Health check: flags companies whose scraper looks broken.

A source that has previously recorded jobs (it's baselined, and
seen_jobs.db has rows for it) but comes back with ZERO jobs on a fresh
fetch is almost always a sign the scraper broke - a redesign changed a
CSS selector, a slug moved, a site started blocking requests - not that
the company genuinely has no openings. This does one fresh fetch per
source (no state is written, no notifications are sent) and reports
anything that regressed to zero, plus anything that errored outright.

Doesn't flag sources that have never had a job recorded - those may
just be a genuinely slow-hiring company, not a broken scraper; there's
nothing to regress *from*.

Run from the project root with:
    python -m scripts.health_check

Takes a while: it does a real fetch for every previously-successful
source, and browser-rendered ones cost ~10s each. Safe to Ctrl+C early -
nothing is written, so nothing is left in a half-done state.
"""

import sys

from tracker import sources, state
from tracker.config import load_config


def check_all(source_cfgs):
    """Returns (broken, errored, ok) - three lists of (name, detail)."""
    state.init_db()
    previously_seen = dict(state.count_by_source())

    broken = []   # had jobs before, zero now - likely a broken scraper
    errored = []  # fetch raised - likely a broken scraper too, just louder
    ok = []

    for cfg in source_cfgs:
        name = cfg.get("name", cfg["type"])
        prior_count = previously_seen.get(name, 0)

        if not state.is_baselined(name) or prior_count == 0:
            continue  # nothing recorded yet - not a regression, skip

        print(f"[{name}] checking ({prior_count} previously recorded)...", file=sys.stderr)
        try:
            jobs = sources.fetch_all_jobs(cfg)
        except Exception as e:
            errored.append((name, str(e)))
            continue

        if len(jobs) == 0:
            broken.append((name, f"had {prior_count} recorded, 0 returned just now"))
        else:
            ok.append((name, len(jobs)))

    return broken, errored, ok


def print_report(broken, errored, ok):
    print(f"\n{'=' * 70}")
    print(f"Health check: {len(ok)} healthy, {len(broken)} regressed to zero, {len(errored)} errored")
    print(f"{'=' * 70}\n")

    if broken:
        print(f"REGRESSED TO ZERO ({len(broken)}) - had jobs before, none now:")
        for name, detail in broken:
            print(f"  [{name}] {detail}")
        print()

    if errored:
        print(f"ERRORED ({len(errored)}) - fetch itself failed:")
        for name, detail in errored:
            print(f"  [{name}] {detail[:150]}")
        print()

    if not broken and not errored:
        print("Nothing looks broken.")


def run():
    cfg = load_config()
    try:
        broken, errored, ok = check_all(cfg["sources"])
        print_report(broken, errored, ok)
    finally:
        sources.close_browser()


if __name__ == "__main__":
    run()
