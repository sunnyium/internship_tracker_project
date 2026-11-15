"""What a posting has to survive to be worth a notification.

    evaluate() | (should_notify, reason) for one posting from one repo

Ordered cheapest and most certain first:

    1. citizenship   US-citizen-only or clearance-required -> drop
    2. location      confidently outside US/Canada -> drop
    3. degree        explicitly Masters/PhD-only -> drop
    4. term          explicitly Fall/Winter/Spring, no Summer -> drop
    5. title         doesn't look like an internship -> drop
    6. keywords      matches a field of interest -> notify

Every check except the first fails open, matching the career-page tracker: a
false positive costs one line in a digest and a false negative costs an
opportunity. The first one fails closed because it is the only genuinely
binary constraint in the candidate profile - a Canadian citizen on an F-1
cannot take a cleared or citizens-only role, so a posting that says so is not
a near miss.

There is no LLM step here. The career-page tracker asks a model about postings
that pass the title check but miss every keyword, using the job description to
decide. These lists carry no descriptions, so the model would be judging a
title it can already be judged on by keyword, and steps 4 and 5 can be turned
off per repo instead - which is the right answer for a list that is already
entirely AI/ML or entirely quant.
"""

import re

from tracker.filters import degree, location, term

# Explicit statements only. "US" or "citizen" alone appear in far too many
# innocent strings ("US-East", "Citizens Bank") to be usable here.
# tracker/filters/degree.py knows about Masters and PhDs and not about MBAs,
# which these lists carry a lot of ("Finance Intern (MBA - Austin, TX)"). Same
# rule as the shared filter: an MBA marker with no bachelor's-eligibility
# signal beside it means the posting isn't for an undergraduate.
MBA_PATTERN = re.compile(r"\b(m\.?b\.?a\.?)\b", re.IGNORECASE)
UNDERGRAD_PATTERN = re.compile(r"\b(bachelor'?s?|undergrad(uate)?|bs|ba|b\.s\.|b\.a\.)\b", re.IGNORECASE)

# Explicit statements only. "US" or "citizen" alone appear in far too many
# innocent strings ("US-East", "Citizens Bank") to be usable here.
CITIZENSHIP_PATTERN = re.compile(
    r"(u\.?s\.?\s*citizen(ship)?\s*(is\s*)?(required|only)"
    r"|must be a u\.?s\.? citizen"
    r"|citizenship\s*(is\s*)?required"
    r"|security clearance"
    r"|active clearance"
    r"|clearance required"
    r"|requires? (an? )?(active |ts/sci |secret )?clearance)",
    re.IGNORECASE,
)


def evaluate(job, repo_cfg, settings):
    """Returns (should_notify, reason). reason is populated either way, so a
    verbose round can log why something was dropped as readily as why it was
    kept."""
    title = job.get("title", "")
    haystack = " ".join([
        title, job.get("notes", ""), job.get("sponsorship", ""),
        job.get("category", ""), job.get("term", ""),
    ])

    if settings.get("citizenship_filter", {}).get("enabled", True):
        match = CITIZENSHIP_PATTERN.search(haystack)
        if match:
            return False, f"Citizenship/clearance requirement: '{match.group(0).strip()}'"

    loc_cfg = settings.get("location_filter", {})
    if loc_cfg.get("enabled"):
        allowed, region = location.is_allowed(
            job.get("location", ""), loc_cfg.get("allowed_regions", ["US", "CA"])
        )
        if not allowed:
            return False, f"Location filter: '{job.get('location', '')}' classified as {region}"
        if region == "UNKNOWN":
            country = location.foreign_country_in_title(title)
            if country:
                return False, f"Location filter: title names {country}"

    if settings.get("degree_filter", {}).get("enabled", True):
        grad_only, reason = degree.is_grad_only(title, job.get("notes", ""))
        if grad_only:
            return False, f"Degree filter: {reason}"
        if MBA_PATTERN.search(title) and not UNDERGRAD_PATTERN.search(haystack):
            return False, f"Degree filter: title targets MBA students: '{title}'"

    if settings.get("term_filter", {}).get("enabled", True):
        wrong_term, reason = term.is_wrong_term(
            title, job.get("notes", ""), job.get("term", ""),
            allowed_terms=settings.get("term_filter", {}).get("allowed_terms", ["summer"]),
            allowed_years=settings.get("term_filter", {}).get("allowed_years", []),
        )
        if wrong_term:
            return False, reason

    if repo_cfg.get("require_internship_title", True):
        hints = settings.get("internship_title_hints", [])
        if not _contains_any(title, hints):
            return False, "Title doesn't look like an internship posting"

    if repo_cfg.get("keyword_match", True):
        keywords = settings.get("keywords", [])
        text = f"{title} {job.get('category', '')} {job.get('notes', '')}"
        hit = _first_hit(text, keywords)
        if not hit:
            return False, "No keyword match"
        return True, f"Matched keyword '{hit.strip()}'"

    return True, f"Curated list: {repo_cfg.get('name', repo_cfg.get('repo', ''))}"


def _contains_any(text, needles):
    """Word-boundary match, not substring - "intern" as a plain substring
    matches inside "International" and "Internal", which turned postings
    like "International Program Coordinator" into false positives."""
    lower = text.lower()
    return any(re.search(rf"\b{re.escape(n.lower())}\b", lower) for n in needles)


def _first_hit(text, keywords):
    lower = f" {text.lower()} "
    for keyword in keywords:
        if keyword.lower() in lower:
            return keyword
    return None
