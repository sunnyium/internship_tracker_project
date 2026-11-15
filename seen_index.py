"""One "have I seen this posting before" memory shared by both halves.

    SeenIndex.load()        | every remembered key, read once per half-round
    index.seen_link(job)    | True if its link or job number is known
    index.seen_text(job)    | True if its company + title is known
    index.add(job)          | remember a posting (buffered)
    index.flush()           | write the buffered keys in one transaction

Why this exists: each half already remembers job ids, but an id only says
"this exact source handed me this exact row". The same posting kept coming
back under a new id, and so got sent again:

  * the same job in two GitHub lists. Ids there include the list name, so a
    job Simplify carried on Monday and jobright copied on Tuesday was "new"
    on both days.
  * the same job on a career page and in a GitHub list. The two halves keep
    separate databases, and dedupe.py only compared postings within a single
    round.
  * a `type: auto` career page that answered through its platform's API one
    round and through a page scrape or a browser render the next. Each route
    builds a different id ("eightfold:qualcomm.com:446722069792" versus
    "auto:Qualcomm:/careers/job/446722069792"), so the whole board looked new.

A posting is recognized here by any of three keys, independent of which
source or route produced it:

    url    the link with tracking parameters stripped
    num    the link's host plus its job number (the last run of 5+ digits in
           the path), which survives the API and the scraped page using
           different paths
    text   company and title, for aggregators that hide every link behind a
           redirect of their own. Kept for TEXT_KEY_DAYS only, so next year's
           "Quant Trader Intern" at the same firm still counts as new.

Lives in data/seen_index.db, covered by the *.db rule in .gitignore. Deleting
it costs nothing worse than the next round re-seeding it from both halves'
id databases (URL keys only).
"""

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from github_boards.normalize import canonical_url
from github_boards.paths import DB_FILE as GITHUB_DB
from tracker.paths import DATA_DIR, DB_FILE as CAREER_DB

DB_PATH = DATA_DIR / "seen_index.db"

# Long enough to cover one hiring cycle's reposts and aggregator lag, short
# enough that the following year's posting with an identical title is news.
TEXT_KEY_DAYS = 180

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_JOB_NUMBER = re.compile(r"\d{5,}")
# Card text that scrapers pick up alongside the title and that changes daily.
_VOLATILE = re.compile(r"\bposted\s+(?:today|yesterday|\d+\+?\s*days?\s+ago)\b.*$", re.I)


def _norm(text):
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def keys_for(job):
    """Every key this posting can be recognized by. Empty only for a row
    with no link, no company and no title, which nothing can match."""
    keys = []
    url = canonical_url(job.get("url", ""))
    if url:
        keys.append(f"url:{url}")
        # Path only: a query string can carry a listing-wide number (Twilio's
        # pid=) that every job on the board shares, which would collapse them
        # all into one. The last run in the path is the job, not the tenant.
        host, _, path = re.sub(r"^https?://", "", url.split("?")[0]).partition("/")
        numbers = _JOB_NUMBER.findall(path)
        if numbers:
            keys.append(f"num:{host}:{numbers[-1]}")
    company = _norm(job.get("company", ""))
    title = _norm(_VOLATILE.sub("", job.get("title", "")))
    if company and title:
        keys.append(f"text:{company}|{title}")
    return keys


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_keys ("
        " key TEXT PRIMARY KEY,"
        " first_seen TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    return conn


def _seed(conn):
    """Fill an empty index from the URLs both halves have already recorded,
    so the repeats stop on the first round rather than after one more cycle
    of them. Text keys can't be rebuilt this way (the career-page database
    stores the source name, not the company as posted), so only URL and
    job-number keys are seeded."""
    keys = set()
    for path in (CAREER_DB, GITHUB_DB):
        if not path.exists():
            continue
        try:
            src = sqlite3.connect(path)
            rows = src.execute("SELECT url FROM seen_jobs").fetchall()
            src.close()
        except sqlite3.Error:
            continue
        for (url,) in rows:
            keys.update(k for k in keys_for({"url": url or ""}) if not k.startswith("text:"))
    conn.executemany("INSERT OR IGNORE INTO seen_keys (key) VALUES (?)", ((k,) for k in keys))
    conn.commit()
    if keys:
        print(f"[seen-index] Seeded {len(keys)} key(s) from existing history.")


class SeenIndex:
    def __init__(self, keys, read_only=False):
        self._keys = keys
        self._pending = set()
        self._read_only = read_only

    @classmethod
    def load(cls, read_only=False):
        conn = _connect()
        if conn.execute("SELECT 1 FROM seen_keys LIMIT 1").fetchone() is None:
            _seed(conn)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=TEXT_KEY_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        keys = {
            k for (k,) in conn.execute(
                "SELECT key FROM seen_keys WHERE key NOT LIKE 'text:%' OR first_seen >= ?", (cutoff,)
            )
        }
        conn.close()
        return cls(keys, read_only)

    def seen_link(self, job):
        """Known by its link or job number - the same posting for certain."""
        return any(k in self._keys for k in keys_for(job) if not k.startswith("text:"))

    def seen_text(self, job):
        """Known by company and title. Weaker than a link match: only ask
        this of a posting that already passed the filters, since a firm's
        London and New York roles can share a title."""
        return any(k in self._keys for k in keys_for(job) if k.startswith("text:"))

    def add(self, job, with_text=True):
        """Remember a posting. Pass with_text=False for one that is clearly
        outside the US/Canada, so its title can't hide a domestic twin."""
        for key in keys_for(job):
            if not with_text and key.startswith("text:"):
                continue
            if key not in self._keys:
                self._keys.add(key)
                self._pending.add(key)

    def flush(self):
        if self._read_only or not self._pending:
            self._pending.clear()
            return
        conn = _connect()
        conn.executemany("INSERT OR IGNORE INTO seen_keys (key) VALUES (?)",
                         ((k,) for k in self._pending))
        conn.commit()
        conn.close()
        self._pending.clear()
