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
    strip_html,
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
            "description": strip_html(j.get("content", ""))[:2000],
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
        desc = strip_html(j.get("descriptionPlain") or j.get("description", ""))
        jobs.append({
            "id": f"lever:{slug}:{j['id']}",
            "title": j.get("text", ""),
            "url": j.get("hostedUrl", ""),
            "company": cfg.get("name", slug),
            "location": (j.get("categories") or {}).get("location", ""),
            "description": desc[:2000],
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


def fetch_workday(cfg):
    tenant = cfg["tenant"]
    site = cfg["site"]
    host = cfg.get("host", "wd1")
    url = f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    jobs = []
    offset = 0
    limit = 20
    for _ in range(10):  # cap pagination so one misbehaving source can't loop forever
        r = requests.post(
            url, headers={**HEADERS, "Content-Type": "application/json"},
            json={"limit": limit, "offset": offset, "searchText": ""},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            path = p.get("externalPath", "")
            jobs.append({
                "id": f"workday:{tenant}:{path}",
                "title": p.get("title", ""),
                "url": f"https://{tenant}.{host}.myworkdayjobs.com/{site}{path}",
                "company": cfg.get("name", tenant),
                "location": p.get("locationsText", ""),
                "description": "",  # Workday list endpoint doesn't include full descriptions
                "posted_at": parse_workday_posted_on(p.get("postedOn")),
            })
        offset += limit
        if len(postings) < limit:
            break
    return jobs
