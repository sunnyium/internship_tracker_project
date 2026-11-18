"""
Best-effort US/Canada location filter.

Job location text varies wildly by source ("San Jose, California, United
States of America", "Austin, TX", "Toronto, ON, Canada", "Remote",
"Bangalore, India", or nothing at all). This does a reasonable job of
classifying it, but it's fundamentally string matching against a curated
list, not a geocoding service - if it ever misfires (e.g. flags a real US
posting as excluded, or vice versa), that's the tradeoff of a lightweight
approach. Given the choice, it's tuned to fail open: anything it can't
confidently classify is KEPT, not dropped.
"""

import re

US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york",
    "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west virginia", "wisconsin", "wyoming", "district of columbia",
}

US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

CANADA_PROVINCE_NAMES = {
    "ontario", "quebec", "british columbia", "alberta", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "prince edward island", "northwest territories", "yukon", "nunavut",
}

CANADA_PROVINCE_ABBR = {
    "ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "NT", "YT", "NU",
}

US_SIGNAL_PHRASES = ["united states", "usa", "u.s.a", "u.s."]
CANADA_SIGNAL_PHRASES = ["canada"]

# Countries and phrases that indicate a location is known but clearly NOT
# US/Canada, used only to raise confidence in the "excluded" classification
# rather than to drive it (the region name lists above do the real work).
# Broad on purpose - every name missing here is a posting that falls through
# to UNKNOWN and gets kept, which is how an obviously-overseas role slips
# past the filter and into a digest.
OTHER_COUNTRY_SIGNAL_PHRASES = [
    "india", "united kingdom", " uk", "germany", "france", "china",
    "singapore", "japan", "australia", "ireland", "netherlands", "spain",
    "italy", "brazil", "mexico", "israel", "poland", "switzerland",
    "korea", "taiwan", "hong kong", "vietnam", "thailand", "indonesia",
    "malaysia", "philippines", "new zealand", "south africa", "nigeria",
    "egypt", "united arab emirates", " uae", "saudi arabia", "qatar",
    "turkey", "russia", "ukraine", "sweden", "norway", "denmark",
    "finland", "belgium", "austria", "portugal", "greece",
    "czech republic", "romania", "hungary", "colombia", "argentina",
    "chile", "peru", "costa rica", "panama", "pakistan", "bangladesh",
    "sri lanka", "nepal", "kenya", "ghana", "morocco", "tunisia",
    "iceland", "luxembourg", "estonia", "latvia", "lithuania", "serbia",
    "croatia", "slovakia", "slovenia", "bulgaria", "cyprus", "malta",
]

# ISO 3166 alpha-3 codes for the countries above that postings use most.
OTHER_COUNTRY_CODES = {
    "DEU", "GBR", "IND", "CHN", "JPN", "SGP", "FRA", "IRL", "ISR", "POL",
    "ESP", "ITA", "NLD", "AUS", "BRA", "MEX", "KOR", "TWN", "HKG", "ROU",
    "CZE", "CHE", "SWE", "NOR", "DNK", "FIN", "BEL", "AUT", "PRT", "GRC",
    "HUN", "ARG", "CHL", "COL", "PER", "CRI", "PHL", "MYS", "THA", "VNM",
    "IDN", "NZL", "ZAF", "ARE", "SAU", "TUR", "EGY", "NGA", "KEN", "PAK",
    "LUX", "EST", "LVA", "LTU", "SRB", "HRV", "SVK", "SVN", "BGR", "UKR",
}

# ISO two-letter codes, minus every one that is also a US state or Canadian
# province code (IN, DE, IL, CA, ...) - those are classified above as US/CA.
OTHER_COUNTRY_ABBR = {
    "GB", "NL", "AU", "SG", "HK", "CN", "JP", "FR", "IE", "CH", "SE", "NO",
    "DK", "FI", "BE", "AT", "PT", "ES", "IT", "PL", "CZ", "RO", "HU", "KR",
    "TW", "NZ", "AE", "BR", "MX", "IS", "LU", "EE", "LT", "LV", "HR", "BG",
    "TR", "ZA", "MY", "TH", "VN", "PH", "ID", "CY", "MT", "GR", "UA", "RS",
}

# Cities that postings name without a country. Finance and tech hubs only;
# names shared with a well-known US or Canadian city are left out unless the
# US/CA checks above always catch that city first (they need its state or
# province beside it, which these lists include when it is the US one).
OTHER_CITY_NAMES = [
    "london", "amsterdam", "rotterdam", "utrecht", "sydney", "melbourne", "brisbane",
    "tel aviv", "herzliya", "haifa", "jerusalem", "paris", "dublin", "zurich", "zug",
    "geneva", "frankfurt", "munich", "berlin", "hamburg", "milan", "madrid",
    "barcelona", "lisbon", "stockholm", "copenhagen", "oslo", "helsinki", "brussels",
    "warsaw", "krakow", "prague", "bucharest", "budapest", "limassol", "vienna",
    "edinburgh", "manchester", "tokyo", "osaka", "seoul", "taipei", "shanghai",
    "beijing", "shenzhen", "hangzhou", "mumbai", "bangalore", "bengaluru",
    "gurgaon", "gurugram", "hyderabad", "pune", "chennai", "noida", "delhi",
    "dubai", "abu dhabi", "doha", "riyadh", "sao paulo", "são paulo",
    "mexico city", "bogota", "buenos aires", "auckland", "kuala lumpur",
    "bangkok", "jakarta", "manila", "ho chi minh",
]

# Region and remote-scope phrases that mean "not US/Canada" without naming a
# specific country - a job board's own shorthand for "everywhere but here".
OTHER_REGION_SIGNAL_PHRASES = [
    "international", "worldwide", "emea", "apac", "latam",
    "remote - international", "remote (international)", "non-us",
    "outside the us", "outside united states", "outside north america",
]


def classify_region(location_text):
    """Returns "US", "CA", "OTHER", or "UNKNOWN"."""
    if not location_text or not location_text.strip():
        return "UNKNOWN"

    text = location_text.strip()
    lower = text.lower()

    if any(p in lower for p in US_SIGNAL_PHRASES):
        return "US"
    if any(p in lower for p in CANADA_SIGNAL_PHRASES):
        return "CA"

    if any(name in lower for name in US_STATE_NAMES):
        return "US"
    if any(name in lower for name in CANADA_PROVINCE_NAMES):
        return "CA"

    # Abbreviation check - case-sensitive, word-boundary, against the
    # original (not lowercased) text, since these only make sense as
    # actual uppercase codes like "Austin, TX".
    tokens = set(re.findall(r"\b[A-Z]{2}\b", text))
    if tokens & US_STATE_ABBR:
        return "US"
    if tokens & CANADA_PROVINCE_ABBR:
        return "CA"

    # Three-letter country codes, as Amazon writes them ("Munich, Bavaria,
    # DEU", "Seattle, WA, USA"). Uppercase whole words only.
    codes = set(re.findall(r"\b[A-Z]{3}\b", text))
    if codes & {"USA"}:
        return "US"
    if codes & {"CAN"}:
        return "CA"
    if codes & OTHER_COUNTRY_CODES:
        return "OTHER"

    if any(p in lower for p in OTHER_COUNTRY_SIGNAL_PHRASES):
        return "OTHER"

    # Two-letter country codes ("London, GB") and finance-hub city names with
    # no country attached ("Amsterdam", "Tel Aviv"), which the global quant
    # lists use constantly. Both run only after every US/Canada check above
    # has failed, so "London, ON", "Paris, TX" and "Melbourne, FL" are
    # already classified by then.
    if tokens & OTHER_COUNTRY_ABBR:
        return "OTHER"
    if any(re.search(rf"\b{re.escape(city)}\b", lower) for city in OTHER_CITY_NAMES):
        return "OTHER"
    if any(p in lower for p in OTHER_REGION_SIGNAL_PHRASES):
        return "OTHER"

    # Location text exists but didn't match anything we recognize (could be
    # a city-only format we don't have a mapping for, "Remote", etc.) -
    # treat as unknown rather than guessing.
    return "UNKNOWN"


def is_allowed(location_text, allowed_regions):
    """Returns (allowed: bool, region: str). UNKNOWN always passes -
    fail-open by design, per the "rather over-notify than miss an
    opportunity" preference this whole filter operates under."""
    region = classify_region(location_text)
    if region == "UNKNOWN":
        return True, region
    return region in allowed_regions, region


def foreign_country_in_title(title):
    """The non-US/Canada country a title names, or "" if none.

    For postings whose location field is empty - the heuristic page scrape
    never fills it - but whose title carries the place anyway: "... - 2027
    Start Singapore", "6 months, Cambridge, United Kingdom". Only country
    names count here, not region words like "International", which appear
    in plenty of US job titles ("International Finance Intern"). A title that
    also names a US or Canadian place is left alone."""
    if not title:
        return ""
    if classify_region(title) in ("US", "CA"):
        return ""
    lower = f" {title.lower()} "
    for phrase in OTHER_COUNTRY_SIGNAL_PHRASES:
        if re.search(rf"\b{re.escape(phrase.strip())}\b", lower):
            return phrase.strip()
    return ""
