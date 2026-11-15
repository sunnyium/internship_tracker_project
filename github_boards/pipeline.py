"""One round: read every configured repository, decide what is worth telling
you about, send a single digest.

    run_once()      | the whole round, returning how many matches it found
    print_counts()  | postings recorded per repo, for the --stats flag

Not an entrypoint. Run run_github_boards.py from the project root instead,
which is what puts the packages on the import path.

A round has the same two stages as the career-page tracker, for the same
reason. Fetching is network waiting and runs several repos at a time; parsing,
filtering and every database write happen afterwards on one thread, in config
order, so no locking is needed anywhere and the log reads top to bottom.

The order inside the processing stage matters:

    age filter    older than max_posting_age_days, where a date exists -> drop
    baseline      first ever read of this repo -> record everything, notify none
    dedupe        already in the database -> skip silently
    relevance     see relevance.py

A posting is marked seen the moment it is examined, before it is judged. A
crash between judging and notifying therefore loses one digest rather than
replaying thousands of postings on the next round, which is the tradeoff the
career-page tracker makes too.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from github_boards import fetch, notifiers, parse_json, parse_markdown, parse_yaml_dir
from github_boards import normalize, relevance, state
from tracker.filters import location

DEFAULT_FETCH_WORKERS = 4
DEFAULT_MAX_AGE_DAYS = 14

# Files read at once inside one yaml_dir repo, on top of the repo-level pool.
# Kept small because they all come from one host.
YAML_FILE_WORKERS = 6

# Candidate listing files for `strategy: auto`, cheapest first: a structured
# file if the repo keeps one, the README if it doesn't.
AUTO_JSON_PATHS = (".github/scripts/listings.json", "listings.json", "data/listings.json")
AUTO_MARKDOWN_PATHS = ("README.md",)

YAML_SUFFIXES = (".yaml", ".yml")


# 1. Fetching
def _raw_key(repo_cfg, path):
    """Cache key for one file. Includes the branch so switching branches in
    the config doesn't inherit the old branch's ETag."""
    return f"{repo_cfg['repo']}@{repo_cfg['branch']}/{path}"


def _read_file(repo_cfg, path, etags, updates, use_cache):
    """(text, was_unchanged) for one file, recording any new ETag in
    `updates` rather than writing it - the caller is on a worker thread and
    SQLite writes belong to the main one."""
    key = _raw_key(repo_cfg, path)
    etag = etags.get(key) if use_cache else None
    text, new_etag = fetch.fetch_file(repo_cfg["repo"], repo_cfg["branch"], path, etag)
    if text is fetch.NOT_MODIFIED:
        return None, True
    if text is None:
        return None, False
    if new_etag:
        updates[key] = new_etag
    return text, False


def _fetch_json(repo_cfg, paths, etags, updates, use_cache):
    for path in paths:
        text, unchanged = _read_file(repo_cfg, path, etags, updates, use_cache)
        if unchanged:
            return None, f"{path} unchanged"
        if text is not None:
            return parse_json.parse(text, repo_cfg["name"]), path
    return [], None


def _fetch_markdown(repo_cfg, paths, etags, updates, use_cache):
    jobs = []
    read = []
    unchanged = 0
    for path in paths:
        text, was_unchanged = _read_file(repo_cfg, path, etags, updates, use_cache)
        if was_unchanged:
            unchanged += 1
            continue
        if text is None:
            continue
        jobs.extend(parse_markdown.parse(text, repo_cfg["name"]))
        read.append(path)
    if not read and unchanged:
        return None, "unchanged"
    if read and not jobs:
        # The file was there and had nothing job-shaped in it. That is what a
        # rewritten README looks like, so say so rather than reporting the
        # repo as quiet.
        return jobs, f"{', '.join(read)} - parsed 0 rows, the layout may have changed"
    return jobs, ", ".join(read) if read else None


def _fetch_yaml_dir(repo_cfg, etags, updates, use_cache):
    """One tree call, then one raw read per company file.

    The tree call is the only thing in this project that touches the REST API,
    which allows 60 requests an hour unauthenticated - fine for a handful of
    repos on this strategy, and the reason file contents are never fetched
    through it."""
    directory = repo_cfg.get("dir", "data").strip("/")
    all_paths, truncated = fetch.list_tree(repo_cfg["repo"], repo_cfg["branch"])
    if truncated:
        print(f"[{repo_cfg['name']}] Tree listing was truncated by GitHub - some files were not read.")

    candidates = [
        p for p in all_paths
        if p.startswith(f"{directory}/") and p.lower().endswith(YAML_SUFFIXES)
    ]
    cap = int(repo_cfg.get("max_files", 150))
    wanted = candidates[:cap]

    # Read the company files several at a time. Sequentially, 58 files at
    # roughly a second each is a minute of a round that otherwise takes ten
    # seconds, and unlike the career-page tracker's browser phase there is
    # nothing here that can't be parallelized.
    jobs = []
    unchanged = 0
    with ThreadPoolExecutor(max_workers=YAML_FILE_WORKERS) as pool:
        reads = [pool.submit(_read_file, repo_cfg, p, etags, updates, use_cache) for p in wanted]
        for path, future in zip(wanted, reads):
            text, was_unchanged = future.result()
            unchanged += 1 if was_unchanged else 0
            if text:
                jobs.extend(parse_yaml_dir.parse_file(text, path))

    if wanted and unchanged == len(wanted):
        return None, "unchanged"
    note = f"{len(wanted)} file(s) under {directory}/, {unchanged} unchanged"
    if len(candidates) > cap:
        note += f" (capped from {len(candidates)}; raise max_files)"
    return jobs, note


def fetch_repo(repo_cfg, etags, use_cache=True):
    """(jobs, etag_updates, note) for one repo. jobs is None when the source
    files are byte-for-byte what we read last time.

    Raises on a real failure so the caller can report which repo broke without
    a broken repo taking the round down with it."""
    updates = {}
    strategy = repo_cfg["strategy"]
    paths = repo_cfg.get("paths") or []

    if strategy == "json":
        jobs, note = _fetch_json(repo_cfg, paths, etags, updates, use_cache)
    elif strategy == "markdown":
        jobs, note = _fetch_markdown(repo_cfg, paths, etags, updates, use_cache)
    elif strategy == "yaml_dir":
        jobs, note = _fetch_yaml_dir(repo_cfg, etags, updates, use_cache)
    elif strategy == "auto":
        jobs, note = _fetch_json(repo_cfg, paths or list(AUTO_JSON_PATHS), etags, updates, use_cache)
        if jobs is not None and not jobs:
            jobs, note = _fetch_markdown(
                repo_cfg, paths or list(AUTO_MARKDOWN_PATHS), etags, updates, use_cache
            )
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    if jobs is not None and not jobs and note is None:
        raise ValueError(
            f"No listing file found in {repo_cfg['repo']} on branch {repo_cfg['branch']}. "
            f"Tried: {', '.join(paths) or 'the strategy defaults'}"
        )
    return jobs, updates, note


def _fetch_all(repo_cfgs, workers, use_cache):
    """{index: (jobs, etag_updates, note, error)} keyed by position in the
    config, so results can be reported in the order the file lists them."""
    # The whole cache in one query rather than a lookup per file: yaml_dir
    # repos don't know their file names until the tree call lands on a worker
    # thread, and SQLite reads belong here on the main one.
    etags = state.all_etags() if use_cache else {}

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(fetch_repo, c, etags, use_cache): i for i, c in enumerate(repo_cfgs)}
        for future in as_completed(pending):
            index = pending[future]
            try:
                jobs, updates, note = future.result()
                results[index] = (jobs, updates, note, None)
            except Exception as e:
                results[index] = (None, {}, None, e)
    return results


# 2. Processing
def _is_recent(job, max_age_days):
    """True when the posting is inside the window, or when the list didn't
    say when it was posted. Undated rows are the norm in half these repos, so
    dropping them would drop the repos."""
    posted_at = job.get("posted_at")
    if posted_at is None:
        return True
    return posted_at >= datetime.now(timezone.utc) - timedelta(days=max_age_days)


def _prepare(job, repo_cfg):
    """Adds the identity and provenance fields the rest of the round needs."""
    job = dict(job)
    job["repo"] = repo_cfg["name"]
    job["id"] = normalize.job_id(
        repo_cfg["name"], job.get("url", ""), job.get("company", ""), job.get("title", "")
    )
    return job


def run_once(cfg, dry_run=False, only=None, notify=True):
    """One full round. Returns the list of (repo_name, job, reason) matches.

    `only` restricts the round to repos whose name or owner/name contains that
    string, which is how a single repo gets tested without waiting on the
    other forty. `dry_run` bypasses the ETag cache, writes nothing and sends
    nothing - it prints the digest that would have gone out instead.

    `notify=False` is for run.py, which runs this round straight after the
    career-page sweep and sends one message covering both."""
    settings = cfg.get("settings", {})
    repo_cfgs = cfg["repos"]
    if only:
        needle = only.lower()
        repo_cfgs = [c for c in repo_cfgs if needle in c["name"].lower() or needle in c["repo"].lower()]
        if not repo_cfgs:
            print(f"No configured repo matches {only!r}.")
            return []

    matches = []
    try:
        _collect_matches(repo_cfgs, settings, matches, dry_run)
    finally:
        if dry_run:
            _print_dry_run(matches)
        elif notify:
            notifiers.notify_all(matches, cfg.get("notifications", {}), len(repo_cfgs))
    return matches


def _collect_matches(repo_cfgs, settings, matches, dry_run):
    """Appends (repo_name, job, reason) for every new relevant posting.

    Takes the list as an argument rather than returning it so an error late in
    the round still leaves the caller holding everything found before it."""
    max_age_days = int(settings.get("max_posting_age_days", DEFAULT_MAX_AGE_DAYS))
    workers = max(1, int(settings.get("max_fetch_workers", DEFAULT_FETCH_WORKERS)))
    verbose = bool(settings.get("verbose_logging", False))

    print(f"Reading {len(repo_cfgs)} repo(s), {workers} at a time...")
    fetched = _fetch_all(repo_cfgs, workers, use_cache=not dry_run)

    seen_ids = state.all_seen_ids()
    baselined = state.baselined_repos()
    # Shared with the career-page half, and across every list here - the
    # per-repo ids alone let one job through once per list it appears in.
    # Imported here rather than at the top: seen_index imports this package.
    import seen_index
    known = seen_index.SeenIndex.load(read_only=dry_run)
    try:
        _process_repos(repo_cfgs, settings, matches, dry_run, fetched,
                       seen_ids, baselined, known, max_age_days, verbose)
    finally:
        known.flush()


def _clearly_abroad(job):
    if location.classify_region(job.get("location", "")) == "OTHER":
        return True
    return bool(location.foreign_country_in_title(job.get("title", "")))


def _process_repos(repo_cfgs, settings, matches, dry_run, fetched,
                   seen_ids, baselined, known, max_age_days, verbose):
    for index, repo_cfg in enumerate(repo_cfgs):
        name = repo_cfg["name"]
        jobs, etag_updates, note, error = fetched[index]

        if error is not None:
            print(f"[{name}] Fetch failed, skipping this round: {error}")
            continue
        if jobs is None:
            print(f"[{name}] Unchanged since last round, nothing to do.")
            continue

        # Every row is recorded, not just recent ones: a row left unrecorded
        # because it was old would look new the day a list re-dated it.
        jobs = [_prepare(j, repo_cfg) for j in jobs]

        if name not in baselined:
            if not dry_run:
                state.mark_seen_many(
                    (j["id"], name, j.get("company", ""), j["title"], j["url"]) for j in jobs
                )
                state.mark_baselined(name)
            baselined.add(name)
            seen_ids.update(j["id"] for j in jobs)
            for j in jobs:
                known.add(j, with_text=not _clearly_abroad(j))
            print(f"[{name}] First read ({note}) - recorded {len(jobs)} existing posting(s) "
                  "as baseline, won't notify for these.")
            _store_etags(etag_updates, dry_run)
            continue

        unseen = [j for j in jobs if j["id"] not in seen_ids]
        old = [j for j in unseen if not _is_recent(j, max_age_days)]
        if old:
            if not dry_run:
                state.mark_seen_many(
                    (j["id"], name, j.get("company", ""), j["title"], j["url"]) for j in old
                )
            seen_ids.update(j["id"] for j in old)
            for j in old:
                known.add(j, with_text=not _clearly_abroad(j))

        new_count = 0
        match_count = 0
        repeat_count = 0
        for job in unseen:
            if job["id"] in seen_ids:
                continue
            if not dry_run:
                state.mark_seen(job["id"], name, job.get("company", ""), job["title"], job["url"])
            seen_ids.add(job["id"])
            # Same posting, already seen in another list or on a career page.
            if known.seen_link(job):
                known.add(job, with_text=False)
                repeat_count += 1
                continue

            try:
                should_notify, reason = relevance.evaluate(job, repo_cfg, settings)
            except Exception as e:
                print(f"[{name}] Error judging '{job['title']}': {e}")
                known.add(job, with_text=False)
                new_count += 1
                continue

            if should_notify and known.seen_text(job):
                known.add(job, with_text=False)
                repeat_count += 1
                continue
            known.add(job, with_text=not _clearly_abroad(job))
            new_count += 1

            if should_notify:
                matches.append((name, job, reason))
                match_count += 1
                print(f"[{name}] MATCH: {job['title']} -> {job['url']}")
            elif verbose:
                print(f"[{name}] Not relevant: {job['title']} ({reason})")

        known.flush()
        print(f"[{name}] {len(jobs)} posting(s) listed, {new_count} new in the last "
              f"{max_age_days} day(s), "
              f"{match_count} relevant"
              + (f", {repeat_count} already seen elsewhere" if repeat_count else "")
              + f" ({note})")
        _store_etags(etag_updates, dry_run)


def _store_etags(updates, dry_run):
    """Written only after the file it belongs to parsed successfully - an
    ETag stored for a file we failed to read would make every later round
    skip it as unchanged."""
    if dry_run:
        return
    for url, etag in updates.items():
        state.set_etag(url, etag)


# 3. Output
def _print_dry_run(matches):
    print(f"\n--- dry run: {len(matches)} match(es), nothing sent, nothing recorded ---")
    if matches:
        print(notifiers.format_digest(matches))


def print_counts():
    """Postings recorded per repo, cumulative across every run."""
    counts = state.count_by_repo()
    if not counts:
        print("No postings recorded yet.")
        return
    print("Postings recorded per repo:")
    for repo_name, count in counts:
        print(f"  {repo_name}: {count}")
