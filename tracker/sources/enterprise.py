"""Large-employer career platforms that don't expose a normal job-board API.

Each of these is a bespoke integration against an endpoint the company's own
frontend calls - none of them is a documented public API, so any of them can
break when the company redeploys. When one starts returning zero jobs or
erroring, the fix is almost always to open the careers page in a browser, watch
the Network tab, and compare the request shape against what's here. The
docstrings say what to look for.

Two kinds live here:

    Single-company    apple, amazon, google - one employer each
    Multi-tenant      oracle_cloud, eightfold, phenom - platforms that power
                      many enterprise career sites, keyed by a per-company
                      site number / domain / ref_num that can usually be
                      auto-discovered but is more reliable set by hand
"""

import re
import uuid

import requests
from bs4 import BeautifulSoup

from tracker.sources.common import (
    HEADERS,
    TIMEOUT,
    parse_epoch_seconds,
    parse_iso,
    parse_month_name_date,
)


def fetch_apple(cfg):
    """Apple's careers site (jobs.apple.com) isn't on Greenhouse, Lever, or
    Workday, and it's a JS-rendered page, so plain HTML scraping finds
    nothing. This calls Apple's own internal search API directly instead.
    Undocumented/unofficial, so it could break if Apple changes their site -
    if this source starts erroring, check jobs.apple.com's network requests
    in a browser dev console to see if the endpoint or payload shape changed.

    Apple's API *requires* at least one location filter - "postLocation-USA"
    covers the whole US. Add more IDs to cfg['locations'] for other
    countries if needed (found via jobs.apple.com's location search box)."""
    url = "https://jobs.apple.com/api/role/search"
    query = cfg.get("query", "intern")
    locations = cfg.get("locations", ["postLocation-USA"])
    jobs = []
    page = 1
    expected_total = None
    for _ in range(25):  # hard cap so a misbehaving response can't loop forever
        body = {
            "query": query,
            "locale": "en-us",
            "filters": {"postingpostLocation": locations},
            "page": page,
        }
        r = requests.post(url, headers={**HEADERS, "Content-Type": "application/json"}, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        results = data.get("searchResults", [])
        if not results:
            break
        before = len(jobs)
        for j in results:
            position_id = j.get("positionId", "")
            jobs.append({
                "id": f"apple:{j.get('id', position_id)}",
                "title": j.get("postingTitle", ""),
                "url": j.get("link") or f"https://jobs.apple.com/en-us/details/{position_id}",
                "company": cfg.get("name", "Apple"),
                "location": ", ".join(loc.get("name", "") for loc in j.get("locations", []) if loc.get("name")),
                "description": (j.get("jobSummary") or "")[:2000],
                "posted_at": parse_iso(j.get("postDateInGMT")),
            })
        expected_total = data.get("totalRecords", expected_total)
        if len(jobs) == before or (expected_total and len(jobs) >= int(expected_total)):
            break
        page += 1
    return jobs


def fetch_amazon(cfg):
    """amazon.jobs' own frontend calls this JSON endpoint for search results -
    it's not an official developer API, but it's the same unauthenticated
    endpoint the public search page itself uses, and has been stable for
    years. posted_date comes as text like 'September 24, 2025'."""
    url = "https://www.amazon.jobs/en/search.json"
    query = cfg.get("query", "intern")
    jobs = []
    offset = 0
    limit = 100
    for _ in range(25):  # hard cap so a misbehaving response can't loop forever
        params = {"base_query": query, "offset": offset, "result_limit": limit, "sort": "recent"}
        r = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        batch = data.get("jobs", [])
        if not batch:
            break
        for j in batch:
            desc = " ".join(filter(None, [j.get("description_short", ""), j.get("basic_qualifications", "")]))
            jobs.append({
                "id": f"amazon:{j.get('id')}",
                "title": j.get("title", ""),
                "url": f"https://www.amazon.jobs{j.get('job_path', '')}",
                "company": cfg.get("name", "Amazon"),
                "location": j.get("normalized_location") or j.get("location", ""),
                "description": desc[:2000],
                "posted_at": parse_month_name_date(j.get("posted_date")),
            })
        offset += limit
        if len(batch) < limit:
            break
    return jobs


def fetch_google(cfg):
    """Google's newer careers site (google.com/about/careers/applications)
    is server-rendered - job data is in the raw HTML, unlike Apple/Tesla/
    Meta. But its CSS classes look auto-generated and likely to change on
    redeploy, so instead of a fragile class-based selector, this matches
    on the URL pattern of job links (/jobs/results/<digits>-<slug>), which
    is far more stable, then walks up to the nearest heading for the title.
    If Google's URL structure ever changes and this starts returning zero
    jobs, that pattern is the first thing to check against the live page."""
    url = cfg["careers_url"]
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    job_link_re = re.compile(r"/jobs/results/\d+-")
    jobs = []
    seen_hrefs = set()
    for a in soup.find_all("a", href=job_link_re):
        href = a["href"]
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        full_url = href if href.startswith("http") else f"https://www.google.com{href}"
        heading = a.find_previous(["h1", "h2", "h3", "h4"])
        title = heading.get_text(" ", strip=True) if heading else a.get_text(" ", strip=True)
        if not title:
            continue
        job_id_match = re.search(r"/jobs/results/(\d+)-", href)
        job_id = job_id_match.group(1) if job_id_match else href
        jobs.append({
            "id": f"google:{job_id}",
            "title": title,
            "url": full_url,
            "company": cfg.get("name", "Google"),
            "location": "",
            "description": "",
            "posted_at": None,  # not exposed on the listing page
        })
    return jobs


def _discover_oracle_site(careers_url):
    """Oracle Recruiting Cloud pages embed a 'siteNumber: CX_XXXXX' string
    in their page JS (or set it as a cookie). Returns (api_domain,
    site_number). api_domain is the resolved host after following any HTTP
    redirects - if the real API lives on a different subdomain reached via
    a client-side JS redirect (not a plain HTTP redirect), this won't catch
    it, which is why cfg['api_domain'] / cfg['site_number'] overrides exist
    as a manual fallback."""
    r = requests.get(careers_url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    domain = re.sub(r"^https?://", "", r.url).split("/")[0]
    match = re.search(r"siteNumber['\"]?\s*[:=]\s*['\"](CX_\d+)['\"]", r.text)
    site_number = match.group(1) if match else r.cookies.get("ORA_CX_SITE_NUMBER")
    return domain, site_number


def fetch_oracle_cloud(cfg):
    """Oracle Recruiting Cloud (ORC) powers Oracle's own careers site plus
    many large companies' career pages (JPMorgan Chase, Goldman Sachs, Ford,
    Marriott, and others all run on it). It's a JS-rendered candidate
    portal, so plain HTML scraping (generic_html) finds nothing - this
    calls the underlying public JSON search API instead.

    Auto-discovers the API domain + site number from cfg['careers_url'].
    If that fails (common - some instances put the real API domain behind
    a client-side JS redirect that a simple request can't follow), open
    the careers page in a browser, open dev tools' Network tab, search a
    job, find the request to 'recruitingCEJobRequisitions', and set
    cfg['api_domain'] (its host) and cfg['site_number'] (its
    'siteNumber=CX_XXXXX' query param) manually to skip auto-discovery."""
    careers_url = cfg["careers_url"]
    domain = cfg.get("api_domain")
    site_number = cfg.get("site_number")
    if not domain or not site_number:
        discovered_domain, discovered_site = _discover_oracle_site(careers_url)
        domain = domain or discovered_domain
        site_number = site_number or discovered_site
    if not site_number:
        raise ValueError(
            "Could not auto-discover Oracle Cloud site number - set "
            "'api_domain' and 'site_number' manually in config/companies.yaml for this "
            "source (see the fetch_oracle_cloud docstring in sources/enterprise.py for "
            "how to find them)"
        )

    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(careers_url)
    base_path = re.sub(r"/jobs/?$", "", parsed.path)
    careers_base = urlunsplit((parsed.scheme, parsed.netloc, base_path, "", ""))

    url = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    headers = {
        **HEADERS,
        "ora-irc-cx-userid": str(uuid.uuid4()),
        "ora-irc-language": "en",
        "content-type": "application/vnd.oracle.adf.resourceitem+json;charset=utf-8",
    }
    keyword = cfg.get("query", "intern")
    limit = 100
    offset = 0
    jobs = []
    for _ in range(25):  # hard cap so a misbehaving response can't loop forever
        params = {
            "onlyData": "true",
            "expand": "requisitionList.workLocation",
            "finder": f"findReqs;siteNumber={site_number},keyword={keyword}",
            "limit": limit,
            "offset": offset,
        }
        r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        page_jobs = items[0].get("requisitionList", [])
        if not page_jobs:
            break
        for j in page_jobs:
            job_id = j.get("Id", "")
            location = j.get("PrimaryLocation", "")
            jobs.append({
                "id": f"oracle:{site_number}:{job_id}",
                "title": j.get("Title", ""),
                "url": f"{careers_base}/job/{job_id}",
                "company": cfg.get("name", "Oracle"),
                "location": location,
                "description": (j.get("ShortDescriptionStr") or "")[:2000],
                "posted_at": parse_iso(j.get("PostedDate")),
            })
        offset += limit
        if len(page_jobs) < limit:
            break
    return jobs


def fetch_eightfold(cfg):
    """Eightfold.ai powers many enterprise career sites, including custom
    domains like careers.appliedmaterials.com (not just the standard
    {company}.eightfold.ai subdomain form). Their public 'SmartApply' JSON
    API returns full job listings including a direct, ready-to-use URL per
    job - no separate URL-building needed.

    Tries the API on the SAME host as cfg['careers_url'] first, since many
    custom-domain Eightfold sites serve the API there too. If that fails
    (some instances only serve the API from the underlying
    {company}.eightfold.ai host, which isn't reliably guessable from a
    custom domain), set cfg['api_host'] manually - open the careers page in
    a browser, check dev tools' Network tab for a request to
    'api/apply/v2/jobs', and copy its host."""
    from urllib.parse import urlsplit, parse_qs

    careers_url = cfg["careers_url"]
    parsed = urlsplit(careers_url)
    query_params = parse_qs(parsed.query)

    api_host = cfg.get("api_host", parsed.netloc)
    domain = cfg.get("domain") or (query_params.get("domain", [None])[0])
    if not domain:
        raise ValueError(
            "Could not determine the 'domain' parameter for this Eightfold source - "
            "set cfg['domain'] manually in config/companies.yaml (it's the '?domain=...' "
            "value in the careers page URL)"
        )
    location = cfg.get("location") or (query_params.get("location", [None])[0]) or ""
    query = cfg.get("query", "intern")

    url = f"https://{api_host}/api/apply/v2/jobs"
    headers = {**HEADERS, "Accept": "application/json"}
    jobs = []
    start = 0
    batch_size = 10
    for _ in range(50):  # hard cap so a misbehaving response can't loop forever
        params = {"domain": domain, "hl": "en", "start": start, "query": query, "location": location}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            if start == 0:
                raise ValueError(
                    f"Eightfold API request failed on host '{api_host}' ({e}). "
                    "This company's Eightfold instance may only serve its API from a "
                    "different host - set cfg['api_host'] manually (see fetch_eightfold "
                    "docstring in sources/enterprise.py)."
                )
            break
        data = r.json()
        positions = data.get("positions", [])
        if not positions:
            break
        for p in positions:
            jobs.append({
                "id": f"eightfold:{domain}:{p.get('id')}",
                "title": p.get("name", ""),
                "url": p.get("canonicalPositionUrl", ""),
                "company": cfg.get("name", domain),
                "location": p.get("location", ""),
                "description": (p.get("job_description") or "")[:2000],
                "posted_at": parse_epoch_seconds(p.get("t_create")),
            })
        start += batch_size
        if len(positions) < batch_size:
            break
    return jobs


def _discover_phenom_refnum(domain):
    r = requests.get(f"https://{domain}/global/en/search-results", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    match = re.search(r"refNum['\"]?\s*[:=]\s*['\"]([A-Za-z0-9_]+)['\"]", r.text)
    return match.group(1) if match else None


def fetch_phenom(cfg):
    """Phenom People powers many enterprise career sites (Cisco, GE
    Aerospace, and others) - identifiable by 'cdn.phenompeople.com' asset
    URLs on the careers page. Calls the site's own '/widgets' search
    endpoint directly.

    Requires a ref_num (a per-company code, e.g. Cisco's is
    'CISCISGLOBAL' - visible in the careers page's asset URLs and job
    codes). If not set in cfg, tries to auto-discover it from the page
    HTML, but this is less reliable than for Oracle/Eightfold since Phenom
    doesn't consistently expose it in a simple regex-friendly spot -
    setting ref_num manually in config/companies.yaml is the more reliable
    path."""
    domain = cfg["domain"]
    ref_num = cfg.get("ref_num") or _discover_phenom_refnum(domain)
    if not ref_num:
        raise ValueError(
            f"Could not auto-discover Phenom ref_num for {domain} - set cfg['ref_num'] "
            "manually in config/companies.yaml (check the site's asset URLs under "
            "cdn.phenompeople.com or job posting codes for a per-company prefix)."
        )

    url = f"https://{domain}/widgets"
    query = cfg.get("query", "intern")
    size = 20
    jobs = []
    for page in range(25):  # hard cap so a misbehaving response can't loop forever
        payload = {
            "lang": "en_global", "deviceType": "desktop", "country": "global",
            "pageName": "search-results", "size": size, "from": page * size,
            "jobs": True, "counts": False, "clearAll": False,
            "keywords": query, "global": True, "selected_fields": {},
            "sort": {"order": "desc", "field": "postedDate"},
            "locationData": {}, "refNum": ref_num, "ddoKey": "refineSearch",
        }
        r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
        batch = data.get("refineSearch", {}).get("data", {}).get("jobs", [])
        if not batch:
            break
        for j in batch:
            title = j.get("title", "")
            job_seq = j.get("jobSeqNo") or j.get("jobId") or j.get("id", "")
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            location = j.get("cityStateCountry") or j.get("locationDisplay") or ""
            jobs.append({
                "id": f"phenom:{ref_num}:{job_seq}",
                "title": title,
                "url": f"https://{domain}/global/en/job/{job_seq}/{slug}",
                "company": cfg.get("name", domain),
                "location": location,
                "description": "",
                "posted_at": parse_iso(j.get("postedDate")),
            })
        if len(batch) < size:
            break
    return jobs
