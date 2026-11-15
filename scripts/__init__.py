"""One-off maintenance tools, each run from the project root as a module:

    python -m scripts.stats             what's been recorded, per company
    python -m scripts.health_check      which scrapers look broken
    python -m scripts.reset_companies   wipe tracked history for named companies

None of them are imported by the tracker itself.
"""
