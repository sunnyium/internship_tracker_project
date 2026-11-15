"""The four standard applicant-tracking systems, all of which publish a real
JSON API: Greenhouse, Lever, Ashby, Workday.

These are the good case. Each one gives back the full listing - title, URL,
location, description, and a genuine posting date - from a single documented
(or at least stable and unauthenticated) endpoint, with no scraping and no
browser. Together they cover most of config/companies.yaml.

Every fetcher here is configured by a short slug or tenant name, not a URL:

    greenhouse / lever / ashby   slug  - the last path segment of the board URL
    workday                      tenant + site (+ host, default "wd1")
"""

import requests

from tracker.sources.common import (
    HEADERS,
    TIMEOUT,
    parse_epoch_millis,
    parse_iso,
    parse_workday_posted_on,
)


def fetch_greenhouse(cfg):
    slug = cfg["slug"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "id": f"greenhouse:{slug}:{j['id']}",
            "title": j.get("title", ""),
            "url": j.get("absolute_url", ""),
            "company": cfg.get("name", slug),
            "location": (j.get("location") or {}).get("name", ""),
            # Raw HTML, turned into text only if the posting turns out to be
            # new (pipeline._ensure_description).
            "description": "",
            "description_html": j.get("content", ""),
            # Greenhouse doesn't expose a separate "first posted" date via
            # this endpoint - updated_at is the closest available signal.
            "posted_at": parse_iso(j.get("updated_at")),
        })
    return jobs


def fetch_lever(cfg):
    slug = cfg["slug"]
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    jobs = []
    for j in data:
        # descriptionPlain is already text; only the HTML fallback needs
        # parsing, and that waits until the posting is known to be new.
        plain = j.get("descriptionPlain") or ""
        jobs.append({
            "id": f"lever:{slug}:{j['id']}",
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "company": cfg.get("name", slug),
            "location": (j.get("categories") or {}).get("location", ""),
            "description": plain[:2000],
            "description_html": "" if plain else j.get("description", ""),
            "posted_at": parse_epoch_millis(j.get("createdAt")),
        })
    return jobs


def fetch_ashby(cfg):
    """Ashby powers a lot of AI-lab and fintech boards (OpenAI, Polymarket,
    Kalshi). Their public posting API returns the full listing - description,
    location and a real publish date - so this is strictly better than
    rendering jobs.ashbyhq.com in a browser, which only ever sees the first
    page of results (OpenAI: 750 jobs here vs 14 via the DOM).

    slug is the last path segment of jobs.ashbyhq.com/<slug>."""
    slug = cfg["slug"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue  # unpublished draft still present in the feed
        jobs.append({
            "id": f"ashby:{slug}:{j.get('id')}",
            "title": j.get("title", ""),
            "url": j.get("jobUrl") or j.get("applyUrl", ""),
            "company": cfg.get("name", slug),
            "location": j.get("location", ""),
            "description": (j.get("descriptionPlain") or "")[:2000],
            "posted_at": parse_iso(j.get("publishedAt")),
        })
    return jobs


# Searched one after another and merged. Workday's search matches words, so
# "intern" alone can miss titles that only say "Internship" or "Co-op".
WORKDAY_QUERIES = ("intern", "internship", "co-op")
WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PAGES = 25


def fetch_workday(cfg):
    """Workday boards, searched for internships rather than read in full.

    Reading the whole board stopped after 10 pages of 20, so at a bank or
    insurer with thousands of openings anything past the newest 200 was never
    seen. Searching returns only the internship-shaped postings, usually in
    a page or two per query. Set `search_queries` on a source to override."""
    tenant = cfg["tenant"]
    site = cfg["site"]
    host = cfg.get("host", "wd1")
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    queries = cfg.get("search_queries") or WORKDAY_QUERIES
    jobs = []
    seen_paths = set()
    for query in queries:
        offset = 0
        for _ in range(WORKDAY_MAX_PAGES):  # cap so one misbehaving source can't loop forever
            r = requests.post(
                url, headers={**HEADERS, "Content-Type": "application/json"},
                json={"limit": WORKDAY_PAGE_SIZE, "offset": offset, "searchText": query},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            postings = r.json().get("jobPostings", [])
            if not postings:
                break
            for p in postings:
                path = p.get("externalPath", "")
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                jobs.append({
                    "id": f"workday:{tenant}:{path}",
                    "title": p.get("title", ""),
                    "url": f"https://{tenant}.{host}.myworkdayjobs.com/{site}{path}",
                    "company": cfg.get("name", tenant),
                    "location": p.get("locationsText", ""),
                    "description": "",  # Workday list endpoint doesn't include full descriptions
                    "posted_at": parse_workday_posted_on(p.get("postedOn")),
                })
            offset += WORKDAY_PAGE_SIZE
            if len(postings) < WORKDAY_PAGE_SIZE:
                break
    return jobs
