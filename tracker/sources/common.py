"""Request settings and date parsing shared by every fetcher.

Each platform hands back its posting date in a different shape - ISO strings,
epoch milliseconds, epoch seconds, "September 24, 2025", "Posted 5 Days Ago" -
so the parsers live here rather than being reinvented per fetcher. All of them
return None rather than raising on anything unparseable: an unknown date means
the posting is kept (see pipeline.is_recent), which is the safe direction.
"""

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "internship-tracker/1.0 (personal job alert script)"}
TIMEOUT = 20


def strip_html(html: str) -> str:
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def parse_iso(dt_str):
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def parse_epoch_millis(ms):
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def parse_epoch_seconds(sec):
    if not sec:
        return None
    try:
        return datetime.fromtimestamp(int(sec), tz=timezone.utc)
    except (ValueError, TypeError, OSError):
        return None


def parse_month_name_date(text):
    """Parses dates like 'September 24, 2025' (used by amazon.jobs)."""
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_workday_posted_on(text):
    """Workday only gives relative text like 'Posted Today', 'Posted
    Yesterday', 'Posted 5 Days Ago', 'Posted 30+ Days Ago' - approximate
    it as a UTC datetime that many days back from right now."""
    if not text:
        return None
    t = text.strip().lower()
    now = datetime.now(timezone.utc)
    if "today" in t:
        return now
    if "yesterday" in t:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\s*\+?\s*days?\s*ago", t)
    if m:
        return now - timedelta(days=int(m.group(1)))
    return None


def origin(url):
    """"https://x.com/a/b?c" -> "https://x.com" (for resolving relative hrefs)."""
    match = re.match(r"^https?://[^/]+", url)
    return match.group(0) if match else url.rstrip("/")


def host(url):
    return re.sub(r"^https?://", "", url).split("/")[0]
