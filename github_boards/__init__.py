"""GitHub job-board watcher.

A second, self-contained tracker that watches crowdsourced internship lists
kept in GitHub repositories (SimplifyJobs, speedyapply, the quant list, the
Canadian lists) instead of company career pages. It has its own config file,
its own database and its own notifiers, and the career-page tracker in
tracker/ neither imports it nor knows it exists.

Package layout:

    paths.py          where this half of the project keeps its files
    config.py         reads config/github_boards.yaml, fills in per-repo defaults
    fetch.py          raw.githubusercontent + the trees API, with ETag caching
    normalize.py      markdown/HTML cell cleaning, date parsing, stable job ids
    parse_json.py     listings.json style files
    parse_markdown.py GitHub-flavoured tables, whatever their column layout
    parse_yaml_dir.py one-YAML-file-per-company repositories
    relevance.py      the filters a posting has to survive to reach you
    state.py          github_jobs.db - seen postings, repo baselines, ETags
    notifiers.py      email digest + ntfy push, one message per round
    pipeline.py       one round: fetch every repo, filter, notify once

The entrypoint is run_github_boards.py at the project root.

The one thing shared with the career-page tracker is tracker/filters - the
US/Canada and Masters/PhD-only classifiers are pure functions with no config
or state behind them, and reimplementing a list of US state abbreviations to
avoid an import would be worse than the coupling.
"""
