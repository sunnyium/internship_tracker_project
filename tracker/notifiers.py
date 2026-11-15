"""Notification channels: an email digest and an ntfy push.

Both fire ONCE PER ROUND, never once per posting. A sweep of ~270 companies can
turn up a dozen matches at once, and a dozen separate pings - especially to a
phone - is unusable. Everything found in a round goes into a single message.
(The one-line-per-job output you see in the terminal is just logging; it has
never been what gets sent.)

When a round finds nothing:

    email   stays silent - an empty inbox is the correct signal
    ntfy    sends a quiet low-priority heartbeat, so "no new jobs" can be told
            apart from "the tracker died three days ago and nobody noticed"

Addresses and credentials come from .env, never from config.yaml. config.yaml
is a committed file; an email address and an app password are not things to
commit. config.yaml keeps only the non-secret settings (SMTP host/port, the
ntfy topic, and the enabled switches).

Each sender is independent and best-effort - a failure in one channel doesn't
stop the other from firing.
"""

import os
import smtplib
import ssl
from collections import namedtuple
from email.mime.text import MIMEText

import requests


def _format_job(job, reason=""):
    lines = [
        f"{job['title']}",
        f"Company: {job['company']}",
    ]
    if job.get("location"):
        lines.append(f"Location: {job['location']}")
    lines.append(f"Link: {job['url']}")
    if reason:
        lines.append(f"Why flagged: {reason}")
    return "\n".join(lines)


def format_digest(matches):
    """matches is a list of (job, reason). One blank line between postings."""
    return "\n\n".join(_format_job(job, reason) for job, reason in matches)


def _summary_line(matches):
    """Short headline used for subjects/titles: '3 new internships' or, for a
    single match, the actual posting so the subject alone is informative."""
    if len(matches) == 1:
        job = matches[0][0]
        return f"New internship: {job['title']} @ {job['company']}"
    companies = sorted({job["company"] for job, _ in matches})
    shown = ", ".join(companies[:3])
    if len(companies) > 3:
        shown += f", +{len(companies) - 3} more"
    return f"{len(matches)} new internships: {shown}"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(matches, cfg):
    """One digest email covering every match in the round. Only called when
    there's something to report - see notify_all."""
    if not cfg.get("enabled"):
        return

    from_address = os.environ.get("EMAIL_FROM_ADDRESS", "").strip()
    app_password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    # Sending to yourself is the common case, so the recipient is optional.
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


# ---------------------------------------------------------------------------
# ntfy push
# ---------------------------------------------------------------------------

def _post_ntfy(cfg, title, body, priority, click_url=None):
    """Shared publisher for both the digest and the heartbeat. Returns quietly
    if ntfy isn't configured - the caller doesn't need to check first."""
    if not cfg.get("enabled"):
        return
    topic = cfg.get("topic", "")
    if not topic or "CHANGE-THIS" in topic:
        print("[ntfy] Skipped - set a unique topic name in config/config.yaml")
        return
    server = cfg.get("server", "https://ntfy.sh").rstrip("/")

    headers = {
        "Title": title.encode("utf-8"),
        "Priority": priority,
    }
    if click_url:
        headers["Click"] = click_url

    try:
        requests.post(
            f"{server}/{topic}",
            data=body.encode("utf-8"),
            headers=headers,
            timeout=15,
        )
        return True
    except Exception as e:
        print(f"[ntfy] FAILED: {e}")
        return False


def send_ntfy(matches, cfg):
    """ntfy.sh - free push notification to phone/desktop, no account needed.
    Install the ntfy app and subscribe to your topic to receive these."""
    # A tap target only makes sense when there's exactly one posting to open.
    click_url = matches[0][0]["url"] if len(matches) == 1 else None
    if _post_ntfy(cfg, _summary_line(matches), format_digest(matches), "high", click_url):
        print(f"[ntfy] Sent digest of {len(matches)} posting(s)")


def send_ntfy_heartbeat(cfg):
    """Sent when a round finishes having found nothing.

    The point is liveness, not information: without it, a tracker that has
    silently crashed looks exactly like a quiet job market. Priority is "low"
    so it lands in the notification list without buzzing the phone.
    """
    if _post_ntfy(
        cfg,
        "Tracker round finished",
        "No new postings this round.",
        "low",
    ):
        print("[ntfy] Sent no-results heartbeat")


# ---------------------------------------------------------------------------

def notify_all(matches, notif_cfg):
    """matches: list of (job, reason) found this round, possibly empty.

    Matches -> one email + one push. Nothing found -> no email at all, just the
    ntfy heartbeat, so an empty inbox always means "nothing new" rather than
    "something broke".
    """
    if matches:
        send_email(matches, notif_cfg.get("email", {}))
        send_ntfy(matches, notif_cfg.get("ntfy", {}))
    else:
        send_ntfy_heartbeat(notif_cfg.get("ntfy", {}))


# ---------------------------------------------------------------------------
# Combined digest - both halves of the project in one message
# ---------------------------------------------------------------------------
#
# run.py sweeps career pages and then GitHub job-board repos, and sends one
# message covering both rather than one message each. Two pings arriving a
# minute apart, from the same tracker, about the same job search, is the thing
# the once-per-round rule exists to prevent.
#
# Sections are pre-formatted by whichever half produced them and are printed in
# the order they are passed in, which is how career-page results end up above
# GitHub results.

# ntfy rejects a body over 4KB, and a combined round is exactly when that gets
# hit. The push carries what fits and the email carries everything.
NTFY_BODY_LIMIT = 3500

# One block of the message. `in_total` is False for the Duplicates block at the
# bottom, which is a record of what was suppressed rather than another five
# postings to go and apply to.
Section = namedtuple("Section", "heading body count in_total")
Section.__new__.__defaults__ = (True,)


def _as_sections(sections):
    return [s if isinstance(s, Section) else Section(*s) for s in sections]


def _combined_body(sections):
    return "\n\n".join(
        f"===== {s.heading} ({s.count}) =====\n\n{s.body}"
        for s in sections if s.count
    )


def _combined_subject(sections):
    """'7 new internships: 5 career pages, 2 GitHub repos'. The breakdown is
    worth the characters - it says at a glance which half is producing."""
    counted = [s for s in sections if s.in_total]
    total = sum(s.count for s in counted)
    parts = [f"{s.count} {s.heading.lower()}" for s in counted if s.count]
    return f"{total} new internship{'s' if total != 1 else ''}: {', '.join(parts)}"


def _fit_for_push(body):
    """The digest trimmed to what ntfy will deliver, cut on posting boundaries
    so the last thing on screen is a pointer to the email rather than half a
    URL."""
    if len(body.encode("utf-8")) <= NTFY_BODY_LIMIT:
        return body
    footer = "\n\n... more in the email digest."
    budget = NTFY_BODY_LIMIT - len(footer.encode("utf-8"))
    kept = []
    used = 0
    for block in body.split("\n\n"):
        cost = len(block.encode("utf-8")) + 2
        if used + cost > budget:
            break
        kept.append(block)
        used += cost
    return "\n\n".join(kept) + footer


def notify_sections(sections, notif_cfg):
    """sections: Section objects, or plain (heading, body, count) tuples, in
    the order they should appear.

    Same contract as notify_all - anything found sends both channels, an empty
    round sends only the ntfy heartbeat - except that the message is assembled
    from sections produced by different trackers."""
    sections = _as_sections(sections)
    total = sum(s.count for s in sections if s.in_total)
    if not total:
        send_ntfy_heartbeat(notif_cfg.get("ntfy", {}))
        return

    body = _combined_body(sections)
    subject = _combined_subject(sections)

    email_cfg = notif_cfg.get("email", {})
    if email_cfg.get("enabled"):
        _send_email_text(subject, body, email_cfg, total)
    if _post_ntfy(notif_cfg.get("ntfy", {}), subject, _fit_for_push(body), "high"):
        print(f"[ntfy] Sent combined digest of {total} posting(s)")


def _send_email_text(subject, body, cfg, count):
    """The send half of send_email, without the digest formatting - the
    combined message is already assembled by the time it gets here."""
    from_address = os.environ.get("EMAIL_FROM_ADDRESS", "").strip()
    app_password = os.environ.get("EMAIL_APP_PASSWORD", "").strip()
    to_address = os.environ.get("EMAIL_TO_ADDRESS", "").strip() or from_address

    if not from_address or not app_password:
        print("[email] Skipped - set EMAIL_FROM_ADDRESS and EMAIL_APP_PASSWORD in .env")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to_address

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(cfg.get("smtp_host", "smtp.gmail.com"), cfg.get("smtp_port", 587)) as server:
            server.starttls(context=context)
            server.login(from_address, app_password)
            server.sendmail(from_address, to_address, msg.as_string())
        print(f"[email] Sent combined digest of {count} posting(s) to {to_address}")
    except Exception as e:
        print(f"[email] FAILED: {e}")
