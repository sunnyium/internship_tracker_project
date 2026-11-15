"""
Quick on-demand check: how many jobs has the tracker recorded per company
so far? Doesn't fetch anything new or send notifications - just reads
data/seen_jobs.db.

Run from the project root with:
    python -m scripts.stats
"""

from tracker import pipeline, state


def run():
    state.init_db()
    pipeline.print_job_counts()


if __name__ == "__main__":
    run()
