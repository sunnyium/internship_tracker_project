"""Reading job rows out of a repository that keeps one YAML file per company.

    parse_file() | every posting in a single company's YAML document

The quant list is built this way: data/jane-street.yaml, data/citadel.yaml and
fifty more, each naming the firm once and then listing role links under short
role codes ("QT", "QR", "SWE", "FPGA"). One file is one company and one link is
one posting, so a firm posting a second quant research role shows up as a new
entry in an existing file rather than as a new file - which is why the fetcher
reads every file each round instead of watching the directory listing.

There are no dates anywhere in this layout. Every posting comes back undated,
which the pipeline treats as "keep", and the dedupe database is what stops a
notification for the fifty roles that were already there.
"""

import yaml

ROLE_LIST_KEYS = ("roles", "positions", "openings", "jobs")
LINK_LIST_KEYS = ("links", "urls", "applications")


def parse_file(text, path=""):
    """Every posting in one company YAML file.

    Returns an empty list for a document that isn't shaped like a company -
    these directories also hold a README and the occasional schema file, and
    a file that doesn't name a company simply isn't one."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(doc, dict):
        return []

    company = str(doc.get("name") or doc.get("company") or "").strip()
    if not company:
        return []

    location = _as_text(doc.get("locations") or doc.get("location"))
    notes = _as_text(doc.get("notes"))
    website = str(doc.get("website") or "").strip()

    jobs = []
    for role in _role_entries(doc):
        role_type = str(role.get("role_type") or role.get("role") or role.get("title") or "").strip()
        for link in _links(role):
            url = str(link.get("url") or link.get("link") or "").strip()
            if not url:
                continue
            label = str(link.get("label") or "").strip()
            title = " - ".join(p for p in (role_type, label) if p) or "Open role"
            jobs.append({
                "company": company,
                "title": f"{title} Internship",
                "location": location,
                "url": url,
                "posted_at": None,
                "term": "",
                "notes": notes[:300],
                "category": role_type,
            })

    # A firm with no structured roles still has a careers page worth one line.
    if not jobs and website:
        jobs.append({
            "company": company,
            "title": "Internship openings",
            "location": location,
            "url": website,
            "posted_at": None,
            "term": "",
            "notes": notes[:300],
            "category": "",
        })
    return jobs


def _role_entries(doc):
    for key in ROLE_LIST_KEYS:
        value = doc.get(key)
        if isinstance(value, list):
            return [r for r in value if isinstance(r, dict)]
    return []


def _links(role):
    for key in LINK_LIST_KEYS:
        value = role.get(key)
        if isinstance(value, list):
            # A bare list of URL strings is as common as a list of dicts.
            return [v if isinstance(v, dict) else {"url": v} for v in value]
    if role.get("url"):
        return [{"url": role["url"]}]
    return []


def _as_text(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v)
    return "" if value is None else str(value)
