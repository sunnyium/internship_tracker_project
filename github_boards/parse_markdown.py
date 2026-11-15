"""Reading job rows out of GitHub-flavoured markdown tables.

    parse() | every posting in a markdown document, whatever its column layout

There is no schema to lean on here. Each list invents its own columns - the
five layouts this was built against head their columns Company/Position/
Location/Salary/Posting/Age, Company/Job Title/Location/Work Model/Date Posted,
Company/Role/Location/Apply/Added, Company/Role/Category/Location/Skills/
Posted/Apply, and Name/Status/Year/Note - so columns are matched by name
against a synonym table rather than by position, and a table whose header
matches nothing is skipped rather than guessed at.

Two conventions are shared by every one of these lists and both are load
bearing. A company cell holding "|->" means "same company as the row above",
so a run of roles at one employer is written once; miss it and every follow-on
row is attributed to nobody. And a locked or struck-out apply cell means the
role is gone, which is the only "this closed" signal these files carry.
"""

import re

from github_boards import normalize

FENCE = re.compile(r"^\s*(```|~~~)")
SEPARATOR_ROW = re.compile(r"^\s*\|?[\s:-]*-{2,}[\s:|-]*\|?\s*$")

# Header text -> canonical field. Matched on the cleaned, lowercased header,
# so "**Apply**" and "Date Posted " both land where they should.
COLUMN_ALIASES = {
    "company": {
        "company", "company name", "employer", "organization", "org", "firm",
        "name", "companies",
    },
    "title": {
        "role", "roles", "position", "positions", "job title", "title", "job",
        "role title", "role/position", "job role", "opportunity",
    },
    "location": {
        "location", "locations", "location(s)", "city", "office", "where",
        "location/s",
    },
    "link": {
        "apply", "application", "application/link", "apply link", "link",
        "links", "posting", "application link", "apply here", "url",
        "actions", "action", "apply now", "listing", "application process",
        "how to apply", "website",
    },
    "date": {
        "date posted", "date", "posted", "posted on", "age", "added",
        "date added", "updated", "last updated", "date updated", "posted date",
        # Program lists date the closing rather than the opening: the whole
        # point of "Microsoft Explore, deadline Fall" is the deadline.
        "deadline", "deadlines", "approximate deadline", "application deadline",
        "due", "due date", "closes", "close date", "open date",
    },
    "term": {
        "term", "terms", "season", "cycle", "year", "semester", "start",
        "timeline", "batch", "duration", "eligibility",
    },
    "status": {"status", "status/open date", "active", "open", "state"},
    "category": {"category", "type", "field", "function", "area", "work model"},
    "notes": {"notes", "note", "details", "description", "comments", "requirements"},
}

# A table needs a subject and at least one job-shaped column beside it. Without
# this, resource tables ("Name | Description" lists of links to other repos)
# parse cleanly into nonsense.
SUPPORTING_FIELDS = ("title", "link", "location", "date", "status", "term")

# Where to look for the posting URL, best first. The company cell is last
# because it usually holds the corporate homepage, which is useless as an
# application link but better than dropping the row.
URL_PRIORITY = ("title", "link", "notes", "location", "date", "company")


def parse(text, repo_name=""):
    """Every posting found in one markdown document.

    `repo_name` is only used for the log line naming a table that looked like
    jobs but produced none, which is the shape a layout change takes."""
    jobs = []
    for header, rows in _iter_tables(text):
        columns = _map_columns(header)
        if not _is_job_table(columns):
            continue
        jobs.extend(_rows_to_jobs(columns, rows))
    return jobs


# 1. Finding the tables
def _split_cells(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", line)]


def _iter_tables(text):
    """Yields (header_cells, [row_cells]) for each table in the document.

    A table is a line containing pipes followed by a |---|---| separator, and
    it runs until the first line with no pipe in it. Fenced code blocks are
    skipped: CONTRIBUTING sections in these repos paste an example row, and
    parsing the example would invent a posting at a company called Example."""
    lines = text.splitlines()
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if FENCE.match(line):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence or "|" not in line or i + 1 >= len(lines):
            i += 1
            continue
        if not SEPARATOR_ROW.match(lines[i + 1]) or "|" not in lines[i + 1]:
            i += 1
            continue

        header = _split_cells(line)
        rows = []
        i += 2
        while i < len(lines):
            row = lines[i].strip()
            if not row or "|" not in row:
                break
            if not SEPARATOR_ROW.match(row):
                rows.append(_split_cells(row))
            i += 1
        yield header, rows


def _map_columns(header_cells):
    """{field: column index} for the columns we recognize. Later duplicates
    lose, so a table with two date-ish columns keeps the leftmost."""
    columns = {}
    for index, cell in enumerate(header_cells):
        name = normalize.clean_text(cell).lower().strip(" :*")
        if not name:
            continue
        for field, aliases in COLUMN_ALIASES.items():
            if name in aliases and field not in columns:
                columns[field] = index
    return columns


def _is_job_table(columns):
    has_subject = "company" in columns or "title" in columns
    return has_subject and any(f in columns for f in SUPPORTING_FIELDS)


# 2. Reading the rows
def _cell(row, columns, field):
    index = columns.get(field)
    if index is None or index >= len(row):
        return ""
    return row[index]


def _pick_url(row, columns):
    """The posting URL, preferring the cell most likely to hold the real one.

    The sweep over unmapped cells at the end is what catches a list that puts
    its apply button under a header nobody else uses. Without it a table can
    parse perfectly and still produce nothing, because every row's only link
    sat in a column called something like "Actions"."""
    for field in URL_PRIORITY:
        urls = normalize.cell_urls(_cell(row, columns, field))
        if urls:
            return urls[0]
    mapped = set(columns.values())
    for index, cell in enumerate(row):
        if index in mapped:
            continue
        urls = normalize.cell_urls(cell)
        if urls:
            return urls[0]
    return ""


def _rows_to_jobs(columns, rows):
    jobs = []
    last_company = ""
    for row in rows:
        if not any(cell.strip() for cell in row):
            continue

        company = normalize.clean_text(_cell(row, columns, "company"))
        if "company" in columns and normalize.is_continuation(company):
            company = last_company
        elif company:
            last_company = company

        title = normalize.clean_text(_cell(row, columns, "title"))
        if not title:
            # Lists of named programs ("Microsoft Explore", "IBM Accelerate")
            # have no separate role column - the one name is the whole posting.
            title = company
        if not title:
            continue

        status_text = " ".join([
            _cell(row, columns, "status"),
            _cell(row, columns, "link"),
            _cell(row, columns, "title"),
        ])
        if normalize.is_closed(status_text):
            continue

        url = _pick_url(row, columns)
        if not url:
            continue # nothing to open, and nothing stable to remember it by

        jobs.append({
            "company": company or title,
            "title": title,
            "location": normalize.clean_text(_cell(row, columns, "location")),
            "url": url,
            "posted_at": normalize.parse_date(_cell(row, columns, "date")),
            "term": normalize.clean_text(_cell(row, columns, "term")),
            "notes": normalize.clean_text(_cell(row, columns, "notes")),
            "category": normalize.clean_text(_cell(row, columns, "category")),
        })
    return jobs
