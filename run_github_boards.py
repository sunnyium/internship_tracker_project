"""
GitHub job-board watcher - entrypoint.

    python run_github_boards.py --once        one sweep of every repo, then exit
    python run_github_boards.py               sweep forever, sleeping between
    python run_github_boards.py --dry-run     print what would be sent, send and
                                              record nothing
    python run_github_boards.py --repo quant  restrict the round to repos whose
                                              name or owner/name contains "quant"
    python run_github_boards.py --stats       postings recorded per repo, no fetch
    python run_github_boards.py --reset NAME  forget one repo, so the next round
                                              re-baselines it from scratch

Separate from run.py on purpose. The career-page tracker and this watcher share
a project root, a .env file and an ntfy topic, and nothing else - either can be
scheduled, stopped or reset without touching the other.

--dry-run is the one to reach for after editing config/github_boards.yaml: it
bypasses the ETag cache, so it re-reads every file even when nothing changed,
and it writes nothing, so a misconfigured repo can't baseline itself into
silence before you have seen its output.

Exit codes (--once only, so a scheduler's "Last Run Result" means something):
    0  the round completed
    1  the round raised before finishing
"""

import argparse
import sys
import time
import traceback
from datetime import datetime

from dotenv import load_dotenv

from github_boards import pipeline, state
from github_boards.config import load_config

load_dotenv() # reads .env in the project root, if present

# These lists carry job titles written with CJK punctuation, accented French
# and the occasional emoji, and a Windows console (or a log file redirected
# from one) encodes as cp1252 by default - printing one such title raises
# UnicodeEncodeError and takes the whole round down with it. Replacing the
# unencodable characters costs a mangled character in a log line; not doing it
# costs the round.
# line_buffering is set for the same reason: scheduled runs redirect stdout to
# a file, and a block-buffered log shows nothing at all until the round ends.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

DEFAULT_INTERVAL_SECONDS = 3600


def parse_args():
    parser = argparse.ArgumentParser(description="Watch GitHub internship lists for new postings.")
    parser.add_argument("--once", action="store_true", help="one sweep, then exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="print matches without sending or recording anything")
    parser.add_argument("--repo", metavar="NAME", help="only check repos matching this substring")
    parser.add_argument("--stats", action="store_true", help="print postings recorded per repo and exit")
    parser.add_argument("--reset", metavar="NAME", help="forget one repo's history, exactly as named in the config")
    return parser.parse_args()


def run_round(cfg, dry_run=False, only=None):
    """One full sweep. Returns True if it completed, False if it raised.

    Timestamped because in scheduled use this output is a log file nobody
    reads until something looks wrong, and "when did this run" is the first
    question."""
    started = datetime.now()
    print(f"\n=== GitHub boards round started {started:%Y-%m-%d %H:%M:%S} ===")
    try:
        found = pipeline.run_once(cfg, dry_run=dry_run, only=only)
        if found == 0:
            print("No new relevant postings this round.")
        completed = True
    except Exception:
        print("Unexpected error during this round:")
        traceback.print_exc()
        completed = False
    minutes = (datetime.now() - started).total_seconds() / 60
    print(f"=== Round finished in {minutes:.1f} min ===")
    return completed


def main():
    args = parse_args()
    state.init_db()

    if args.stats:
        pipeline.print_counts()
        return 0

    if args.reset:
        deleted = state.delete_repo_records(args.reset)
        print(f"Forgot {deleted} posting(s) for {args.reset!r}. The next round will re-baseline it.")
        return 0

    cfg = load_config()
    repo_count = len(cfg["repos"])

    if args.once or args.dry_run:
        print(f"Single sweep over {repo_count} repo(s).")
        return 0 if run_round(cfg, args.dry_run, args.repo) else 1

    interval = int(cfg.get("settings", {}).get("poll_interval_seconds", DEFAULT_INTERVAL_SECONDS))
    print(f"GitHub board watcher started. Checking {repo_count} repo(s) every {interval}s.")
    print("Press Ctrl+C to stop.")
    while True:
        run_round(cfg, args.dry_run, args.repo)
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
