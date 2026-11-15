"""Tracks which job postings we've already seen, so we never notify twice,
and tracks which sources have been "baselined" so the first successful
check of a source doesn't blast you with every pre-existing posting."""

import sqlite3

from tracker.paths import DB_FILE as DB_PATH


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_jobs (
            job_id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            url TEXT,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS source_baseline (
            source_name TEXT PRIMARY KEY,
            baselined_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def all_seen_ids() -> set:
    """Every job_id on record, in one query.

    A round examines tens of thousands of postings. Querying the database for
    each one would open, query and close a separate connection every time, so
    load the set once per round and check membership in memory instead - the table
    is small enough (a few thousand rows of short strings) that holding it is
    free, and it turns the hottest path in the sweep into a hash lookup.
    """
    conn = sqlite3.connect(DB_PATH)
    ids = {row[0] for row in conn.execute("SELECT job_id FROM seen_jobs")}
    conn.close()
    return ids


def baselined_sources() -> set:
    """Every source name that has completed a first successful pass. Same
    one-query-instead-of-N reasoning as all_seen_ids()."""
    conn = sqlite3.connect(DB_PATH)
    names = {row[0] for row in conn.execute("SELECT source_name FROM source_baseline")}
    conn.close()
    return names


def mark_seen(job_id: str, source: str, title: str, url: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO seen_jobs (job_id, source, title, url) VALUES (?, ?, ?, ?)",
        (job_id, source, title, url),
    )
    conn.commit()
    conn.close()


def mark_seen_many(rows):
    """Record many postings in one transaction. rows is an iterable of
    (job_id, source, title, url).

    Used for baselining, where a single source can contribute several hundred
    postings at once and doing them one connection at a time is the slowest
    thing in a first run. The incremental path deliberately still uses
    mark_seen() one at a time, so a crash mid-round can't replay notifications
    for postings it had already examined."""
    rows = list(rows)
    if not rows:
        return
    conn = sqlite3.connect(DB_PATH)
    conn.executemany(
        "INSERT OR IGNORE INTO seen_jobs (job_id, source, title, url) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def is_baselined(source_name: str) -> bool:
    """True once we've successfully done one full pass over this source -
    meaning any job already sitting in it at that point is a "pre-existing"
    posting, not a new one."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT 1 FROM source_baseline WHERE source_name = ?", (source_name,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_baselined(source_name: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO source_baseline (source_name) VALUES (?)",
        (source_name,),
    )
    conn.commit()
    conn.close()


def count_by_source():
    """Total jobs ever recorded (baseline + new) per source, as a list of
    (source_name, count) tuples sorted by count descending."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "SELECT source, COUNT(*) FROM seen_jobs GROUP BY source ORDER BY COUNT(*) DESC"
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_source_records(source_name: str) -> int:
    """Deletes all seen_jobs + baseline records for a given source name
    (e.g. 'Microsoft'). Returns how many seen_jobs rows were removed.
    Next run will re-baseline that source from scratch - existing postings
    won't trigger notifications, only ones that appear after that."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM seen_jobs WHERE source = ?", (source_name,))
    deleted_count = cur.rowcount
    conn.execute("DELETE FROM source_baseline WHERE source_name = ?", (source_name,))
    conn.commit()
    conn.close()
    return deleted_count
