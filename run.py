"""
Internship Tracker - entrypoint.

    python run.py            check forever, sleeping poll_interval_seconds
                             between rounds. Ctrl+C to stop.

    python run.py --once     do exactly one sweep, then exit.

    python run.py --skip-github    career pages only, no GitHub repos

One round now covers both halves of the project, in this order:

    1. career pages     ~1,100 companies, 10-15 minutes  (tracker/)
    2. GitHub repos     crowdsourced internship lists     (github_boards/)

and sends ONE message covering both: a single list, most relevant posting
first (see ranking.py), each as "Company: Title" and its link. Two pushes a
minute apart about the same job search would defeat the once-per-round rule
the notifiers were built around. Either half failing still lets the other
report - a broken GitHub round does not cost you the career-page digest.

Use --once with Windows Task Scheduler (or cron). When a scheduler owns the
timing, the process should do one sweep and get out of the way rather than
sitting resident for days - it survives reboots, it can't drift, and a hung
round can be killed by the scheduler instead of silently wedging forever.
See README.md for the Task Scheduler walkthrough, and docs/GITHUB_BOARDS.md
for the GitHub half.

Exit codes (--once only, so the scheduler's "Last Run Result" is meaningful):
    0  the round completed
    1  the round raised before finishing
"""

import os
import sys
import time
import traceback
from datetime import datetime

from dotenv import load_dotenv

import dedupe
import ranking
from github_boards import pipeline as gh_pipeline
from github_boards import state as gh_state
from github_boards.config import load_config as load_github_config
from tracker import notifiers, pipeline, state
from tracker.config import load_config
from tracker.sources import rendering

load_dotenv()  # reads .env in the project root, if present

# These lists carry job titles written with CJK punctuation, accented French
# and the occasional emoji. A Windows console, and a log file redirected from
# one, encodes as cp1252 and raises UnicodeEncodeError on the first such title,
# which would take down a round that had already done all its work. Line
# buffering is for the scheduled case, where a block-buffered log shows nothing
# until the round ends.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def _startup_warnings(cfg, ai_api_key):
    if cfg.get("ai_classification", {}).get("enabled") and not ai_api_key:
        print("WARNING: AI double-check is enabled but GROQ_API_KEY is not set.")
        print("         Postings that miss every keyword will be skipped.")

    # Anything that needs a real browser: explicit `type: browser` sources
    # always render; `auto` sources only fall back to rendering when
    # browser_rendering.enabled is on.
    wants_browser = (cfg.get("browser_rendering", {}).get("enabled")
                     or any(s.get("type") == "browser" for s in cfg["sources"]))
    if wants_browser and not rendering.is_available():
        print("WARNING: JavaScript-rendered sources are configured but Playwright isn't installed.")
        print("         Those sources will fail until you run:")
        print("           .venv\\Scripts\\python.exe -m playwright install chromium")


def _career_page_entries(cfg, ai_api_key):
    """Matches from the career-page half, tagged for the digest, or None if it
    raised.

    The exception is swallowed here rather than in run_round so a failure in
    one half still lets the other report. Whatever it found before raising is
    already lost to the dedupe database either way, so reporting the half that
    worked beats reporting nothing at all."""
    try:
        matches = pipeline.run_once(cfg, ai_api_key, notify=False)
    except Exception:
        print("Career-page sweep failed:")
        traceback.print_exc()
        return None
    return [dedupe.Entry("Career pages", job.get("company", ""), job, reason)
            for job, reason in matches]


def _github_entries(gh_cfg):
    """Matches from the GitHub half, tagged for the digest, or None if it
    raised."""
    try:
        matches = gh_pipeline.run_once(gh_cfg, notify=False)
    except Exception:
        print("GitHub repo sweep failed:")
        traceback.print_exc()
        return None
    return [dedupe.Entry("GitHub repos", repo, job, reason)
            for repo, job, reason in matches]


def _ranked_jobs(career, github, cfg):
    """Every posting to send, best match first.

    Career entries go in ahead of GitHub ones so that, when both halves found
    the same posting this round, the company's own link is the copy kept.
    The repeats are dropped silently."""
    unique, duplicates = dedupe.split_duplicates(career + github)
    if duplicates:
        print(f"[dedupe] {len(duplicates)} posting(s) listed by more than one source, sent once")
    ranked = ranking.rank(unique, cfg)
    if len(ranked) < len(unique):
        print(f"[ranking] {len(unique) - len(ranked)} lower-tier posting(s) left out (ranking.send_tiers)")
    return [e.job for e in ranked]


def run_round(cfg, ai_api_key, gh_cfg=None):
    """One full sweep of both halves. Returns True if it completed.

    Timestamped because in scheduled use the output is a log file nobody reads
    until something looks wrong, and "when did this run" is the first question.
    """
    started = datetime.now()
    print(f"\n=== Round started {started:%Y-%m-%d %H:%M:%S} ===")
    completed = True
    try:
        career = _career_page_entries(cfg, ai_api_key)
        completed = career is not None

        github = None
        if gh_cfg is not None:
            print("\n--- GitHub job-board repos ---")
            github = _github_entries(gh_cfg)
            completed = completed and github is not None

        jobs = _ranked_jobs(career or [], github or [], cfg)
        if not jobs:
            print("No new relevant postings this round.")
        # One message for the whole round, most relevant first. An empty round
        # sends only the ntfy heartbeat.
        notifiers.notify_ranked(jobs, cfg["notifications"])
        pipeline.print_job_counts()
    except Exception:
        print("Unexpected error during this round:")
        traceback.print_exc()
        completed = False
    minutes = (datetime.now() - started).total_seconds() / 60
    print(f"=== Round finished in {minutes:.1f} min ===")
    return completed


def _load_github_half(skip):
    """The GitHub config, or None when that half is switched off or missing.

    A missing or broken github_boards.yaml is a warning rather than a failure:
    the career-page tracker predates it and has to keep running without it."""
    if skip:
        return None
    try:
        gh_cfg = load_github_config()
    except FileNotFoundError:
        print("WARNING: config/github_boards.yaml not found - skipping the GitHub repo half.")
        return None
    except Exception as e:
        print(f"WARNING: config/github_boards.yaml could not be read ({e}) - skipping the GitHub repo half.")
        return None
    gh_state.init_db()
    return gh_cfg


def main():
    args = sys.argv[1:]
    run_once_only = "--once" in args

    state.init_db()
    cfg = load_config()
    ai_api_key = os.environ.get("GROQ_API_KEY", "")
    _startup_warnings(cfg, ai_api_key)
    gh_cfg = _load_github_half("--skip-github" in args)
    gh_count = len(gh_cfg["repos"]) if gh_cfg else 0

    if run_once_only:
        print(f"Single sweep over {len(cfg['sources'])} career page(s) and {gh_count} GitHub repo(s).")
        return 0 if run_round(cfg, ai_api_key, gh_cfg) else 1

    interval = cfg.get("poll_interval_seconds", 180)
    print(f"Internship tracker started. Checking {len(cfg['sources'])} career page(s) "
          f"and {gh_count} GitHub repo(s) every {interval}s.")
    print("Press Ctrl+C to stop.")

    while True:
        run_round(cfg, ai_api_key, gh_cfg)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
