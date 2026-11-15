"""Cheap rejects, applied to a posting before the LLM classifier is ever
called.

Every filter here is deliberately fail-open: anything it can't confidently
classify is KEPT. A false positive costs one line in a digest email; a false
negative costs an opportunity, which is the whole point of running this.

    location.is_allowed(text, regions)             -> (allowed, region)
    degree.is_grad_only(title, desc)                -> (grad_only, reason)
    term.is_wrong_term(title, desc, term, allowed)  -> (wrong_term, reason)
"""

from tracker.filters import degree, location, term

__all__ = ["degree", "location", "term"]
