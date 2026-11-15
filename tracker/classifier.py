"""
AI double-check: for jobs that look like internships but didn't match any
keyword, ask an LLM whether they're plausibly relevant. Biased toward
"yes" - a false positive costs you one email, a false negative costs you
an opportunity.

Uses Groq's free API (OpenAI-compatible endpoint) - no credit card needed.
Get a free key at https://console.groq.com/keys
"""

import os
import json
import requests

API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You screen internship postings for one person.

They are studying: Data Science, Computational and Applied Mathematics, \
Computer Science, and Statistics.

They're interested in roles in: AI/ML, cybersecurity, finance, analyst roles \
(business/data/financial/research analyst), or ANYTHING technical that's \
related in any way to their fields of study above - this is intentionally \
broad, not limited to that exact list.

You will be given a job title and (maybe) a short description. Decide if this \
posting is plausibly relevant, even loosely (e.g. "Product Analytics Intern" \
counts as analyst/data-adjacent; "Trading Strategy Intern" counts as \
finance/quant; "Operations Research Intern" counts as applied math adjacent; \
"Hardware Engineering Intern" counts as technical/CS-adjacent).

Bias strongly toward YES when uncertain - missing a real opportunity is much \
worse than one extra notification. Only say no for postings clearly outside \
any technical or quantitative field entirely (e.g. sales, retail, hospitality, \
general marketing with no data/technical component).

Respond with ONLY valid JSON, no other text: {"relevant": true or false, "reason": "one short sentence"}"""


def is_relevant(title: str, description: str, api_key: str, model: str) -> tuple[bool, str]:
    if not api_key:
        # No API key configured - fail open (treat as relevant) since the
        # user said they'd rather over-notify than miss something.
        return True, "AI check skipped (no API key set) - flagged to be safe"

    user_content = f"Title: {title}\nDescription: {description[:1500] if description else '(none provided)'}"

    try:
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 150,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"].strip()
        # Strip accidental code fences
        text = text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(text)
        return bool(parsed.get("relevant", True)), parsed.get("reason", "")
    except Exception as e:
        # Fail open on any error (network issue, bad JSON, etc.)
        return True, f"AI check errored ({e}) - flagged to be safe"
