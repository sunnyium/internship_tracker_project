"""Turning whatever a repository writes into the fields the pipeline needs.

Cell contents:
    clean_text() | visible text of a markdown/HTML fragment, emoji removed
    cell_urls()  | the real links in a fragment, badge and icon images dropped
    is_closed()  | whether a row has been struck out, locked or marked expired

Dates:
    parse_date()   | one datetime out of the dozen shapes these lists use
    from_epoch()   | seconds or milliseconds, whichever the file meant

Identity:
    canonical_url() | the same posting written two ways collapses to one string
    job_id()        | stable hash, so a row keeps its identity across rounds

The hard part is that none of this is a format. These are hand-maintained
markdown tables: the same column can hold `**[Stripe](https://stripe.com)**`,
`<a href="..."><strong>Stripe</strong></a>`, or the bare word Stripe, and the
apply cell is usually a shields.io badge image wrapped in the link that
actually matters. Everything here returns a best effort rather than raising -
a row that yields no date is kept (pipeline can't verify its age either way),
and a row that yields no link is dropped, because a posting with no URL has
nothing to notify about and no stable identity to remember it by.
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone

# Pictographs, dingbats, flags and variation selectors. Accented Latin is
# deliberately left alone: "Stagiaire en Developpement" arrives from the
# Canadian lists spelled properly and should stay that way.
EMOJI_PATTERN = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF\U0000FE0F\U00002190-\U000021FF\U00002300-\U000023FF]+"
)

MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
MD_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\(\s*<?([^)\s>]+)[^)]*\)")
HTML_TAG = re.compile(r"<[^>]+>")
HTML_HREF = re.compile(r"""<a\s[^>]*href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
BARE_URL = re.compile(r"https?://[^\s<>\)\]|]+")

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
BADGE_HOSTS = (
    "img.shields.io", "shields.io", "i.imgur.com", "imgur.com", "badgen.net",
    "camo.githubusercontent.com", "raw.githubusercontent.com",
    "github.com/user-attachments",
)

# Markers a list uses to say a role is gone. The lock emoji is the convention
# in the Simplify-descended repos; the words cover everyone else.
CLOSED_MARKERS = ("\U0001F512", "❌", "closed", "expired", "no longer accepting", "filled", "inactive")

# A row whose company cell is one of these means "same company as above", a
# convention shared by every markdown list here.
CONTINUATION_MARKERS = ("↳", "⤷", "→", "->", "''", '"', "same")

TRACKING_PARAMS = ("utm_", "gh_src", "ref_", "source=git")


# 1. Cell contents
def clean_text(cell: str) -> str:
    """Visible text of a markdown/HTML table cell, collapsed to one line."""
    if not cell:
        return ""
    text = MD_IMAGE.sub(" ", cell)
    text = MD_LINK.sub(r"\1", text)
    text = HTML_TAG.sub(" ", text)
    text = EMOJI_PATTERN.sub(" ", text)
    text = text.replace("\\|", "|").replace("**", "").replace("__", "")
    text = text.replace("`", "").replace("*", "").replace("~~", "")
    return re.sub(r"\s+", " ", text).strip()


def _is_asset(url: str) -> bool:
    lower = url.lower()
    if lower.endswith(IMAGE_SUFFIXES):
        return True
    return any(h in lower for h in BADGE_HOSTS)


def cell_urls(cell: str) -> list:
    """Every real destination link in a cell, in the order written.

    Badge and icon images are dropped, which is the whole point: an apply cell
    is normally `[![Apply](https://img.shields.io/...)](https://real.job/123)`
    and the shields.io URL is the one thing in it nobody wants."""
    if not cell:
        return []
    found = []
    # Images first, so their src never reaches the markdown-link pass below.
    stripped = MD_IMAGE.sub(" ", cell)
    for _, url in MD_LINK.findall(stripped):
        found.append(url)
    found.extend(HTML_HREF.findall(cell))
    remainder = MD_LINK.sub(" ", stripped)
    remainder = HTML_TAG.sub(" ", remainder)
    found.extend(BARE_URL.findall(remainder))

    urls = []
    for url in found:
        url = url.strip().strip("<>").rstrip(",.")
        if not url.lower().startswith(("http://", "https://")):
            continue # relative image paths and #anchors, never a job posting
        if _is_asset(url) or url in urls:
            continue
        urls.append(url)
    return urls


def is_closed(text: str) -> bool:
    """True when a row says the role is no longer open."""
    if not text:
        return False
    lower = text.lower()
    return any(m in lower for m in CLOSED_MARKERS)


def is_continuation(company_text: str) -> bool:
    """True for the "same company as the row above" placeholder."""
    if not company_text:
        return True
    stripped = company_text.strip()
    return stripped in CONTINUATION_MARKERS or stripped.lower() in CONTINUATION_MARKERS


# 2. Dates
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# "3d", "12h", "45m", "2mo", "1y" - the compact ages speedyapply and zapply
# print. `m` is read as minutes and `mo` as months: on a list sorted newest
# first the bare form always turns out to be minutes, and reading a month as a
# minute keeps an old posting (one extra line in a digest) while the opposite
# mistake would hide a fresh one.
RELATIVE_COMPACT = re.compile(r"^(\d+)\s*(mo|min|[smhdwy])\b", re.IGNORECASE)
# The "+" in "30+ days ago" is Workday-speak for "at least", and reading it as
# exactly 30 is the direction that keeps a posting rather than hiding it.
RELATIVE_WORDS = re.compile(
    r"(\d+)\s*\+?\s*(second|minute|hour|day|week|month|year)s?\s*ago", re.IGNORECASE
)
UNIT_DAYS = {"s": 0, "m": 0, "min": 0, "h": 0, "d": 1, "w": 7, "mo": 30, "y": 365}
WORD_DAYS = {
    "second": 0, "minute": 0, "hour": 0, "day": 1,
    "week": 7, "month": 30, "year": 365,
}


def from_epoch(value):
    """A datetime from an epoch number, guessing seconds vs milliseconds.

    listings.json files use seconds; a few smaller repos copy the shape but
    store milliseconds. Anything past the year 2200 in seconds is milliseconds."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    if number > 7_258_118_400: # 2200-01-01 in seconds
        number /= 1000
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_date(text):
    """UTC datetime for a date cell, or None if it can't be read.

    None is the honest answer for "Winter", "?" and "TBD", all of which appear
    in these tables, and the pipeline keeps undated postings rather than
    guessing at their age."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return from_epoch(text)

    raw = clean_text(str(text))
    if not raw:
        return None
    lower = raw.lower()
    now = datetime.now(timezone.utc)

    if lower in ("today", "new", "just posted", "now"):
        return now
    if lower == "yesterday":
        return now - timedelta(days=1)

    match = RELATIVE_WORDS.search(lower)
    if match:
        return now - timedelta(days=int(match.group(1)) * WORD_DAYS[match.group(2)])

    match = RELATIVE_COMPACT.match(lower)
    if match:
        unit = match.group(2).lower()
        return now - timedelta(days=int(match.group(1)) * UNIT_DAYS[unit])

    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        y, m, d = (int(g) for g in match.groups())
        return _safe_date(y, m, d)

    match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", raw)
    if match:
        year = int(match.group(3))
        return _safe_date(year + 2000 if year < 100 else year, int(match.group(1)), int(match.group(2)))

    # "Aug 7, 2026", "August 07 2026", "Aug 09" - the year is optional because
    # jobright prints "Aug 09" and lets the reader assume the current cycle.
    match = re.search(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*,)?(?:\s+(\d{4}))?", raw)
    month = _month_number(match.group(1)) if match else None
    if month:
        day = int(match.group(2))
        if match.group(3):
            return _safe_date(int(match.group(3)), month, day)
        return _infer_year(month, day, now)

    # "7 Aug 2026"
    match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\.?\s+(\d{4})", raw)
    month = _month_number(match.group(2)) if match else None
    if month:
        return _safe_date(int(match.group(3)), month, int(match.group(1)))

    return None


def _month_number(name):
    """Month for "Aug", "August" or "Sept", or None if that isn't a month.
    Four letters first so "sept" resolves before "sep" gets a chance."""
    if not name:
        return None
    lower = name.lower().rstrip(".")
    return MONTHS.get(lower[:4]) or MONTHS.get(lower[:3])


def _safe_date(year, month, day):
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def _infer_year(month, day, now):
    """A month and day with no year mean the most recent time that date
    happened. Two days of slack absorbs the timezone gap between a list
    generated in some other zone and a round running in UTC."""
    candidate = _safe_date(now.year, month, day)
    if candidate is None:
        return None
    if candidate > now + timedelta(days=2):
        return _safe_date(now.year - 1, month, day)
    return candidate


# 3. Identity
def canonical_url(url: str) -> str:
    """The comparable form of a posting URL.

    Tracking parameters are stripped because jobright rewrites them per
    generated README, and a job whose only change is `utm_campaign` is not a
    new job."""
    if not url:
        return ""
    url = url.strip()
    base, _, query = url.partition("?")
    base = base.split("#")[0].rstrip("/")
    kept = [p for p in query.split("&") if p and not any(t in p.lower() for t in TRACKING_PARAMS)]
    scheme, _, rest = base.partition("://")
    if rest:
        host, _, path = rest.partition("/")
        base = f"{scheme.lower()}://{host.lower()}" + (f"/{path}" if path else "")
    return base + ("?" + "&".join(sorted(kept)) if kept else "")


def job_id(repo_name: str, url: str, company: str = "", title: str = "") -> str:
    """Stable id for one posting within one repo.

    Keyed on the repo as well as the posting, so each list keeps its own
    record of what it has shown. Whether the job was already seen in another
    list or on a career page is decided separately, by seen_index.py."""
    key = canonical_url(url) or f"{company}|{title}".lower()
    digest = hashlib.sha1(f"{repo_name}|{key}".encode("utf-8")).hexdigest()
    return f"gh:{digest[:20]}"
