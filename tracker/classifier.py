"""
AI double-check: for jobs that look like internships but didn't match any
keyword, ask an LLM whether they're plausibly relevant. The prompt is biased
toward "yes" for postings it can actually judge.

When the check can't run at all - no API key, a network error, a retired
model (Groq answers 404 for a model it no longer serves) - the posting is
NOT sent. These are postings that already missed every keyword, and sending
all of them whenever the API is down is how a digest filled up with "AI check
errored - flagged to be safe" lines. Each failure kind is logged once per run.

Uses Groq's free API (OpenAI-compatible endpoint) - no credit card needed.
Get a free key at https://console.groq.com/keys
"""

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


_reported_errors = set()


def _report_once(kind, message):
    if kind not in _reported_errors:
        _reported_errors.add(kind)
        print(f"[ai-check] {message}")


def is_relevant(title: str, description: str, api_key: str, model: str) -> tuple[bool, str]:
    if not api_key:
        _report_once("no-key", "GROQ_API_KEY is not set - postings that miss every keyword are being skipped.")
        return False, "AI check skipped (no API key set)"

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
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        hint = (f" - model '{model}' is probably retired; set ai_classification.model in "
                "config/config.yaml to a current one from console.groq.com/docs/models"
                if status == 404 else "")
        _report_once(f"http-{status}", f"Groq returned HTTP {status}{hint}. Affected postings are skipped.")
        return False, f"AI check errored (HTTP {status})"
    except Exception as e:
        _report_once(type(e).__name__, f"AI check failed ({e}). Affected postings are skipped.")
        return False, f"AI check errored ({e})"
