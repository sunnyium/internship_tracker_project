"""Internship tracker.

Package layout:

    paths.py        where everything lives on disk - the one place that knows
    config.py       reads config/config.yaml + config/companies.yaml
    pipeline.py     one polling round: fetch, filter, classify, notify
    state.py        seen_jobs.db - what we've already looked at
    classifier.py   the LLM double-check for near-miss postings
    notifiers.py    email digest + ntfy push, one message per round
    filters/        cheap rejects applied before the LLM is ever called
    sources/        one fetcher per job-board platform, plus auto-detection

The entrypoint is run.py at the project root; the one-off tools live in
scripts/.
"""
