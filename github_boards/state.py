"""What this watcher remembers between rounds, in its own SQLite file.

    Postings:  all_seen_ids() | mark_seen() | mark_seen_many()
    Baselines: baselined_repos() | mark_baselined() | delete_repo_records()
    ETags:     get_etag() | set_etag()

Three things are stored and they answer three different questions. seen_jobs
answers "have I already told you about this", repo_baseline answers "is this
the first time I have ever read this list", and http_cache answers "has the
file changed since I last read it".

The baseline is what makes a first run quiet. These lists hold thousands of
open postings; without recording the first successful read as pre-existing,
adding a repo would fire a digest with a thousand lines in it.

Deliberately a separate database from the career-page tracker's seen_jobs.db.
Deleting this file re-baselines the GitHub half and leaves the other one alone.
"""

import sqlite3

from github_boards.paths import DB_FILE as DB_PATH


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = _connect()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_id TEXT PRIMARY KEY,
            repo TEXT,
            company TEXT,
            title TEXT,
            url TEXT,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repo_baseline (
            repo_name TEXT PRIMARY KEY,
            baselined_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS http_cache (
            url TEXT PRIMARY KEY,
            etag TEXT,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


# 1. Postings
def all_seen_ids() -> set:
    """Every job_id on record, in one query. A round examines tens of
    thousands of rows and almost all of them are already known, so this is a
    hash lookup per row instead of a connection per row."""
    conn = _connect()
    ids = {row[0] for row in conn.execute("SELECT job_id FROM seen_jobs")}
    conn.close()
    return ids


def mark_seen(job_id, repo, company, title, url):
    conn = _connect()
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs (job_id, repo, company, title, url) VALUES (?, ?, ?, ?, ?)",
        (job_id, repo, company, title, url),
    )
    conn.commit()
    conn.close()


def mark_seen_many(rows):
    """Record many postings in one transaction, for baselining a repo whose
    list is thousands of rows long. The incremental path stays one-at-a-time
    so a crash mid-round can't replay notifications for rows it had already
    examined."""
    rows = list(rows)
    if not rows:
        return
    conn = _connect()
    conn.executemany(
        "INSERT OR IGNORE INTO seen_jobs (job_id, repo, company, title, url) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def count_by_repo():
    """(repo, count) for every repo, most postings first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT repo, COUNT(*) FROM seen_jobs GROUP BY repo ORDER BY COUNT(*) DESC"
    ).fetchall()
    conn.close()
    return rows


# 2. Baselines
def baselined_repos() -> set:
    conn = _connect()
    names = {row[0] for row in conn.execute("SELECT repo_name FROM repo_baseline")}
    conn.close()
    return names


def mark_baselined(repo_name):
    conn = _connect()
    conn.execute("INSERT OR IGNORE INTO repo_baseline (repo_name) VALUES (?)", (repo_name,))
    conn.commit()
    conn.close()


def delete_repo_records(repo_name) -> int:
    """Wipes one repo's history so the next round re-baselines it. Returns how
    many postings were forgotten. Used after fixing a repo's config, where the
    old rows were parsed wrong and shouldn't suppress the corrected ones."""
    conn = _connect()
    cur = conn.execute("DELETE FROM seen_jobs WHERE repo = ?", (repo_name,))
    deleted = cur.rowcount
    conn.execute("DELETE FROM repo_baseline WHERE repo_name = ?", (repo_name,))
    conn.commit()
    conn.close()
    return deleted


# 3. ETags
def all_etags() -> dict:
    """Every stored ETag in one query. The yaml_dir strategy reads dozens of
    files per repo and their names aren't known until the tree call, so
    loading the whole table up front is what lets those files be requested
    conditionally too."""
    conn = _connect()
    etags = dict(conn.execute("SELECT url, etag FROM http_cache"))
    conn.close()
    return etags


def get_etag(url):
    conn = _connect()
    row = conn.execute("SELECT etag FROM http_cache WHERE url = ?", (url,)).fetchone()
    conn.close()
    return row[0] if row else None


def set_etag(url, etag):
    """Only ever called after a file parsed successfully. Storing it earlier
    would let a round that failed to parse claim the file is up to date and
    skip it on every subsequent round."""
    if not etag:
        return
    conn = _connect()
    conn.execute(
        "INSERT INTO http_cache (url, etag, fetched_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(url) DO UPDATE SET etag = excluded.etag, fetched_at = CURRENT_TIMESTAMP",
        (url, etag),
    )
    conn.commit()
    conn.close()
