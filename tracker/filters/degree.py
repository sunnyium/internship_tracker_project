"""
Degree-level filter: excludes postings explicitly aimed ONLY at Masters/PhD
students, keeps everything else.

Design principles (matching the tracker's overall fail-open philosophy):
- Only exclude when the posting EXPLICITLY signals grad-only (e.g. "PhD
  Intern", "Masters Intern - Quant Research", "must be enrolled in a PhD
  program").
- If a posting mentions Masters/PhD alongside Bachelor's-level terms
  (e.g. "Student Researcher, BS/MS" or "pursuing a Bachelor's or Master's
  degree"), it's bachelor's-eligible -> KEEP.
- Softened language ("PhD preferred") is not a hard requirement -> KEEP.
- No degree mention at all, or anything ambiguous -> KEEP.
"""

import re

# Grad-level tokens. Deliberately does NOT include bare "ms" (too ambiguous:
# Mississippi, Microsoft, milliseconds) - "ms/phd", "msc", "m.s." are the
# unambiguous forms.
GRAD_PATTERN = re.compile(
    r"\b(ph\.?d|doctoral|doctorate|master'?s|msc|m\.s\.|ms/phd|phd/ms)\b",
    re.IGNORECASE,
)

# Bachelor's/undergrad tokens - presence of any of these alongside a grad
# token means the posting is bachelor's-eligible, so we keep it.
UNDERGRAD_PATTERN = re.compile(
    r"\b(bachelor'?s?|undergraduate|undergrad|bs|ba|b\.s\.|b\.a\.|bs/ms|bs/ba)\b",
    re.IGNORECASE,
)

# Softened-requirement language: "PhD preferred" is not "PhD required".
SOFTENER_PATTERN = re.compile(r"\bprefer|\bideal|\ba plus\b|\bnice to have\b", re.IGNORECASE)

# Strong grad-only requirement phrasings for description text. Description
# checks are held to a higher bar than title checks, because descriptions
# are long, messy, often truncated, and routinely mention degrees in
# non-restrictive ways.
DESCRIPTION_REQUIREMENT_PATTERN = re.compile(
    r"(enrolled in|pursuing|working toward[s]?|candidate for|must (be|have|hold)|currently in)"
    r"[^.]{0,60}?"
    r"\b(ph\.?d|doctoral|doctorate|master'?s|msc|m\.s\.)\b",
    re.IGNORECASE,
)


def is_grad_only(title, description=""):
    """Returns (grad_only: bool, reason: str). True means the posting is
    explicitly Masters/PhD-only and should be excluded. Anything ambiguous
    returns False (keep) - fail-open by design."""
    title = title or ""
    description = description or ""

    title_has_grad = bool(GRAD_PATTERN.search(title))
    combined = f"{title} {description}"
    has_undergrad_anywhere = bool(UNDERGRAD_PATTERN.search(combined))

    # Title explicitly names a grad degree, no bachelor's-eligibility signal
    # anywhere, and no softening language ("preferred") -> exclude.
    if title_has_grad and not has_undergrad_anywhere and not SOFTENER_PATTERN.search(title):
        return True, f"Title explicitly targets Masters/PhD: '{title}'"

    # Description states a hard grad-degree requirement and nothing anywhere
    # suggests bachelor's students are eligible -> exclude.
    desc_match = DESCRIPTION_REQUIREMENT_PATTERN.search(description)
    if desc_match and not has_undergrad_anywhere and not SOFTENER_PATTERN.search(desc_match.group(0)):
        return True, f"Description requires a grad degree: '{desc_match.group(0).strip()}'"

    return False, ""
