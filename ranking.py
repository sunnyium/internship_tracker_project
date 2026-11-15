"""Orders a round's matches from most to least likely to interest you.

    rank(entries, cfg)  | entries sorted best-first, with lowest tiers dropped
                          if `ranking.send_tiers` says so

Every match is scored on its title, with the posting's category/notes as a
weaker second signal:

    tier 1  the target lanes: quant, data science, AI/ML, forward-deployed
    tier 2  close neighbours: software, data engineering/analytics, research,
            statistics, security
    tier 3  everything else that got through the filters (analyst, finance,
            general engineering)

Inside a tier, a title hit beats a category/notes-only hit, a keyword match
beats one let through by the AI check, and the rest keeps the order it was
found in (career pages before GitHub lists).

The tier keyword lists live in config/config.yaml under `ranking` so they can
be tuned without touching code; DEFAULT_TIERS is only the fallback.
"""

import re

DEFAULT_TIERS = [
    [  # 1 - target lanes
        "quant", "quantitative", "trading", "trader", "algorithmic", "market making",
        "data science", "data scientist",
        "machine learning", "ml", "ai", "artificial intelligence", "deep learning",
        "llm", "nlp", "computer vision", "applied scientist", "research scientist",
        "forward deployed", "fde",
    ],
    [  # 2 - close neighbours
        "software engineer", "software engineering", "software developer", "swe",
        "data engineer", "data analyst", "analytics", "data",
        "research", "statistic", "mathemat", "algorithm",
        "cybersecurity", "security", "infrastructure", "backend", "platform",
    ],
]


def _compile(tiers):
    """Whole-word patterns, except entries ending in a word stem
    ("statistic", "mathemat") which may continue."""
    compiled = []
    for words in tiers:
        parts = []
        for w in words:
            w = w.strip().lower()
            if not w:
                continue
            tail = r"\w*" if w in ("statistic", "mathemat", "quant") else r"\b"
            parts.append(rf"\b{re.escape(w)}{tail}")
        compiled.append(re.compile("|".join(parts), re.I) if parts else None)
    return compiled


def _tier(text, patterns):
    for i, pattern in enumerate(patterns, start=1):
        if pattern is not None and pattern.search(text):
            return i
    return len(patterns) + 1


def score(job, reason, patterns):
    """Lower sorts first."""
    title_tier = _tier(job.get("title", ""), patterns)
    extra = " ".join(str(job.get(k, "")) for k in ("category", "notes"))
    extra_tier = _tier(extra, patterns) + 0.5 if extra.strip() else len(patterns) + 1
    tier = min(title_tier, extra_tier)
    ai_only = 1 if str(reason).startswith("AI double-check") else 0
    return tier, ai_only


def rank(entries, cfg):
    """entries: objects with .job and .reason (dedupe.Entry). Returns them
    best-first, keeping only tiers listed in ranking.send_tiers."""
    rcfg = (cfg or {}).get("ranking", {}) or {}
    patterns = _compile(rcfg.get("tiers") or DEFAULT_TIERS)
    send = rcfg.get("send_tiers")
    scored = []
    for order, entry in enumerate(entries):
        tier, ai_only = score(entry.job, entry.reason, patterns)
        if send and int(tier) not in send:
            continue
        scored.append(((tier, ai_only, order), entry))
    scored.sort(key=lambda pair: pair[0])
    return [entry for _, entry in scored]
