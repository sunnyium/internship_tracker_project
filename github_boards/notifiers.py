"""Notification channels for the GitHub watcher: an email digest and an ntfy
push.

    notify_all() | one email and one push per round, never one per posting

Same two channels and the same once-per-round rule as the career-page tracker,
and deliberately the same ntfy topic, so one subscription on the phone covers
both halves. Every title here starts with "GitHub boards" - when a push
arrives it should be obvious which watcher sent it without opening anything.

Matches are grouped by repository in the digest. Which list a posting came from
is real information: something in the Canadian list is there because it is
Canadian, and something in the quant list is there because it is quant.

Addresses and credentials come from .env, never from the YAML, which is a
committed file. This module reads EMAIL_FROM_ADDRESS, EMAIL_APP_PASSWORD and
EMAIL_TO_ADDRESS - the same three the career-page tracker uses, so configuring
one configures both.

The message itself is assembled and sent by tracker/notifiers.py, which owns
the section format shared with the combined run.py digest. What lives here is
everything specific to this half: how a GitHub posting reads, and the fact
that a posting carried by six of the fifty lists is shown once with the rest
collected under Duplicates.

Each sender is independent and best-effort: a failure in one channel never
stops the other from firing.
"""

import os
import smtplib
import ssl
from collections import OrderedDict
from email.mime.text import MIMEText

import requests

import dedupe
from tracker import notifiers as tracker_notifiers

TITLE_PREFIX = "GitHub boards"

# ntfy rejects a message body over 4KB. A round that surfaces sixty postings
# would sail past that and the push would simply never arrive, so the phone
# gets as much as fits and the email carries the rest.
NTFY_BODY_LIMIT = 3500


def _format_job(job, reason=""):
    lines = [job["title"]]
    company = job.get("company") or ""
    # Program lists have one name per row and nothing else - repeating it as a
    # company line says nothing.
    if company and company != job["title"]:
        lines.append(f"Company: {company}")
    if job.get("location"):
        lines.append(f"Location: {job['location']}")
    lines.append(f"Link: {job['url']}")
    if reason:
        lines.append(f"Why flagged: {reason}")
    return "\n".join(lines)


def format_digest(matches):
    """The body of both messages: a list of (repo_name, job, reason), grouped
    under the repo that surfaced each posting."""
    grouped = OrderedDict()
    for repo_name, job, reason in matches:
        grouped.setdefault(repo_name, []).append((job, reason))

    blocks = []
    for repo_name, entries in grouped.items():
        body = "\n\n".join(_format_job(job, reason) for job, reason in entries)
        blocks.append(f"--- {repo_name} ({len(entries)}) ---\n{body}")
    return "\n\n".join(blocks)


def _summary_line(matches):
    """Subject and push title. A single match names itself, because a subject
    line that says "1 new posting" wastes the only part of an email that gets
    read on a lock screen."""
    if len(matches) == 1:
        job = matches[0][1]
        return f"{TITLE_PREFIX}: {job['title']} @ {job.get('company') or 'unknown'}"
    companies = sorted({job.get("company") or "unknown" for _, job, _ in matches})
    shown = ", ".join(companies[:3])
    if len(companies) > 3:
        shown += f", +{len(companies) - 3} more"
    return f"{TITLE_PREFIX}: {len(matches)} new postings: {shown}"


# 1. Email
def send_email(matches, cfg):
    """One digest email covering every match in the round. Only called when
    there is something to report - see notify_all."""
    if not cfg.get("enabled"):
        return

    from_address = os.environ.get("EMAIL_FROM_ADDRESS", "").strip()
    app_password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    to_address = os.environ.get("EMAIL_TO_ADDRESS", "").strip() or from_address

    if not from_address or not app_password:
        print("[email] Skipped - set EMAIL_FROM_ADDRESS and EMAIL_APP_PASSWORD in .env")
        return

    msg = MIMEText(format_digest(matches))
    msg["Subject"] = _summary_line(matches)
    msg["From"] = from_address
    msg["To"] = to_address

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"), cfg.get("smtp_port", 587)) as server:
            server.starttls(context=context)
            # Gmail authenticates as the sending account, so from_address and
            # the app password have to belong to the same mailbox.
            server.login(from_address, app_password)
            server.sendmail(from_address, to_address, msg.as_string())
        print(f"[email] Sent digest of {len(matches)} posting(s) to {to_address}")
    except Exception as e:
        print(f"[email] FAILED: {e}")


# 2. ntfy push
def _post_ntfy(cfg, title, body, priority, click_url=None):
    if not cfg.get("enabled"):
        return False
    topic = cfg.get("topic", "")
    if not topic or "CHANGE-THIS" in topic:
        print("[ntfy] Skipped - set a topic in config/github_boards.yaml")
        return False
    server = cfg.get("server", "https://ntfy.sh").rstrip("/")

    headers = {"Title": title.encode("utf-8"), "Priority": priority}
    if click_url:
        headers["Click"] = click_url

    try:
        requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=15)
        return True
    except Exception as e:
        print(f"[ntfy] FAILED: {e}")
        return False


def _fit_for_push(matches):
    """The digest, trimmed to what ntfy will actually deliver.

    Postings are dropped from the end rather than the body being cut mid-word,
    so the last thing on the screen is a count of what didn't fit instead of
    half a URL."""
    body = format_digest(matches)
    if len(body.encode("utf-8")) <= NTFY_BODY_LIMIT:
        return body
    kept = matches
    while kept:
        kept = kept[:-1]
        trimmed = format_digest(kept)
        footer = f"\n\n... and {len(matches) - len(kept)} more - see the email digest."
        if len((trimmed + footer).encode("utf-8")) <= NTFY_BODY_LIMIT:
            return trimmed + footer
    return f"{len(matches)} new postings - see the email digest."


def send_ntfy(matches, cfg):
    click_url = matches[0][1]["url"] if len(matches) == 1 else None
    if _post_ntfy(cfg, _summary_line(matches), _fit_for_push(matches), "high", click_url):
        print(f"[ntfy] Sent digest of {len(matches)} posting(s)")


def send_ntfy_heartbeat(cfg, repos_checked):
    """Sent when a round finishes having found nothing.

    Liveness, not information: a watcher that crashed three days ago and a
    quiet week look identical from the phone otherwise. Low priority, so it
    lands in the notification list without buzzing."""
    if not cfg.get("heartbeat", True):
        return
    if _post_ntfy(
        cfg,
        f"{TITLE_PREFIX}: round finished",
        f"No new postings across {repos_checked} repo(s).",
        "low",
    ):
        print("[ntfy] Sent no-results heartbeat")


# 3.
def notify_all(matches, notif_cfg, repos_checked=0):
    """matches: list of (repo_name, job, reason) found this round, possibly
    empty. Matches send both channels; an empty round sends only the
    heartbeat, so an empty inbox always means "nothing new" rather than
    "something broke".

    Fifty lists overlap heavily, so a posting carried by six of them is shown
    once, under the first list that had it, and the other five are listed in a
    Duplicates block at the bottom. Repos are read in config order, so "first"
    means the list ranked highest in github_boards.yaml."""
    if not matches:
        send_ntfy_heartbeat(notif_cfg.get("ntfy", {}), repos_checked)
        return

    entries = [dedupe.Entry("GitHub repos", repo, job, reason) for repo, job, reason in matches]
    unique, duplicates = dedupe.split_duplicates(entries)

    sections = [tracker_notifiers.Section(
        "GitHub repos",
        format_digest([(e.source, e.job, e.reason) for e in unique]),
        len(unique),
    )]
    if duplicates:
        sections.append(tracker_notifiers.Section(
            "Duplicates", dedupe.format_duplicates(duplicates), len(duplicates), False
        ))
        print(f"[dedupe] {len(duplicates)} posting(s) already listed elsewhere, moved to the Duplicates block")
    tracker_notifiers.notify_sections(sections, notif_cfg)
