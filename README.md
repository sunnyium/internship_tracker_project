# Internship Tracker

Scrapes company career pages every few minutes, flags postings that match your
fields of interest, and notifies you by email and phone push — usually within
minutes of a posting going live.

One round now covers two kinds of source:

1. **Career pages** — ~1,100 companies, scraped directly. This document.
2. **GitHub job-board repos** — 51 crowdsourced internship lists
   (SimplifyJobs, speedyapply, the quant list, the Canadian lists, the
   underclassmen lists). See [docs/GITHUB_BOARDS.md](docs/GITHUB_BOARDS.md).

Both run inside `run.py`, so `run_once.bat` and the scheduled task cover both,
and both land in **one** email and **one** push per round: a single list,
most relevant posting first, with anything found in more than one place shown
once.

## How it decides "relevant"

Tuned for someone studying **Data Science, Computational and Applied
Mathematics, Computer Science, and Statistics**, interested in **AI/ML,
cybersecurity, finance, analyst roles, or anything technical related to
those fields** - and only in the **US and Canada**.

1. **Location filter** — if the posting's location is confidently
   identifiable and outside the US/Canada, it's dropped immediately (before
   any AI call, to save cost). If no location is given, or it can't be
   confidently classified, the posting is **kept** - per your preference for
   excess notifications over missed opportunities. See `location_filter` in
   `config/config.yaml` to adjust allowed regions or disable this entirely.
   When the location field is empty (page scrapes never fill it), a title
   that names another country ("... - 2027 Start Singapore") is dropped too.
2. **Term filter** — only Summer, and only the years in
   `term_filter.allowed_years` (2027 and 2028). "Fall 2027" and "Summer 2026"
   are dropped; a title that names no season or year is kept.
3. **Degree filter** — postings explicitly aimed only at Masters/PhD
   students ("PhD Intern", "must be enrolled in a PhD program") are dropped.
   Postings that mention grad degrees alongside Bachelor's-eligibility
   ("BS/MS"), soften the requirement ("PhD preferred"), or don't specify a
   level at all are **kept** - when unsure, it lets the posting through.
4. Title must look like an internship (`intern`, `internship`, `co-op`,
   `student researcher`).
5. **Keyword pass** — if the title/description contains any of your keywords
   (edit the list in `config/config.yaml`), it's flagged immediately, no AI call needed.
6. **AI double-check** — anything that passed step 4 but missed every keyword
   (e.g. "Operations Research Intern" doesn't literally contain "math" or
   "analyst") gets sent to a free LLM (via [Groq](https://groq.com), no
   credit card required) to judge, instructed to cast a wide net across your
   fields of study and interests. If the check can't run (no `GROQ_API_KEY`,
   a network error, or a retired model, which Groq answers with a 404), the
   posting is **skipped**, not sent, and the log says why once per round.

## Only new postings trigger a notification

The first time the program checks a given source, it silently records
everything currently listed there as a baseline — it won't blast you with
notifications for internships that have been posted for weeks. From then on,
only postings that show up *after* that baseline (i.e. genuinely new since
the last check) get notified. This baseline is remembered in
`data/seen_jobs.db`,
so stopping and restarting the program later won't cause re-notifications
for things you've already seen — only truly new postings fire an alert.

"Seen before" is checked across **both** halves and every source, in
`data/seen_index.db` (`seen_index.py`). A posting counts as already seen if
its link (tracking parameters stripped), its job number, or its company and
title were seen anywhere before. That catches the same job reappearing in
another GitHub list, on the company's own page after a list carried it, or
under a different id because a career page answered through its API one round
and a page scrape the next. The company + title match expires after 180 days,
so next year's identically named posting still counts as new.

On top of that, `max_posting_age_hours` in `config/config.yaml` (24, the past day) filters
out anything older than that, based on the actual posting date where the
platform provides one:

- **Greenhouse / Lever** — exact timestamps, filtered precisely.
- **Workday** — only gives relative text ("Posted Today", "Posted 3 Days
  Ago"), so this is an approximation but reliable enough for a 24h cutoff.
- **generic_html / browser / the `auto` fallback scrape** — listing pages
  rarely expose a parseable date at all, so this filter is skipped for those
  and you fall back on the baseline/dedupe behavior above.

## Setup

This machine has several Python installs (an ARM64 3.13, a Store 3.11, and a
uv-managed one). Use a project venv so it doesn't matter which one is on PATH:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python.exe -m playwright install chromium
```

```bash
copy .env.example .env
```

Everything below assumes the venv's interpreter. In VS Code, pick it once via
**Python: Select Interpreter** → `.venv\Scripts\python.exe`, and the Run button
plus the configs in `.vscode/launch.json` will use it automatically.

Fill in `.env`:
- `GROQ_API_KEY` — free, no credit card required. Sign up and grab a key at [console.groq.com/keys](https://console.groq.com/keys) (only needed for the AI double-check step; the free tier's rate limits are generous enough for this use case)
- `EMAIL_FROM_ADDRESS` / `EMAIL_APP_PASSWORD` — the Gmail account that sends the digests, plus an [app password](https://myaccount.google.com/apppasswords) for it (not the account password; enter it without spaces)
- `EMAIL_TO_ADDRESS` — where digests are delivered. Leave blank to send to yourself

## Configure your sources

Edit `config/companies.yaml` (not `config/config.yaml` - that file holds settings like
keywords and notifications; `config/companies.yaml` is the actual list of
companies, kept separate since it's the file you'll keep adding to).
**Start with `type: auto`** for any new company - just give it a URL and a name:

```yaml
- type: auto
  name: "Some Company"
  url: "https://careers.somecompany.com/jobs"
  query: "intern"
```

It tries, in order: recognizable URL patterns (Greenhouse/Lever/Workday/Apple
- no extra request needed), then content signatures on the page itself
(Phenom People, Oracle Recruiting Cloud, Eightfold.ai), then a generic
heuristic scrape that matches job-shaped links directly. This covers most
companies without you needing to know or guess what platform they run on.

If every one of those comes up empty and browser rendering is enabled (see
below), `auto` falls back to loading the page in a real headless browser and
trying the last two strategies again on the rendered DOM. That's what makes
JavaScript-heavy sites work.

## JavaScript-rendered career pages

Plenty of career sites (Meta, TikTok, Snap, Atlassian, Uber, Dropbox, OpenAI)
ship an empty HTML shell and draw the job list with JavaScript afterwards, so
`requests` + BeautifulSoup see nothing no matter what selector you give them.
Those are handled by rendering the page in a headless Chromium first. One-time
setup:

```bash
.venv\Scripts\python.exe -m playwright install chromium
```

(The `playwright` package itself is already in `requirements.txt`; that command
just downloads the browser binary, once, to a shared user-level cache.)

Then either leave `browser_rendering.enabled: true` in `config/config.yaml` (which
lets any `type: auto` source fall back to rendering when it finds nothing), or
mark a source explicitly - preferred once you know it needs a browser, since
it skips the wasted plain-HTTP attempts:

```yaml
- type: browser
  name: "Some Company"
  url: "https://careers.somecompany.com/jobs"
```

Options, all optional, settable globally in `config/config.yaml` or per source:

| Option | What it's for |
|---|---|
| `wait_for_selector` | CSS selector to wait for - the most reliable "the list has arrived" signal |
| `wait_after_load_ms` | Extra wait after the page settles (default 4000). Only applied when `wait_for_selector` is set, when job links never appeared, or when a source sets it itself |
| `timeout_ms` | Page-load timeout (default 30000) |
| `scroll_times` | Scroll to the bottom N times, for lists that lazy-load as you scroll |
| `click_selector` + `max_clicks` | Click a "Load more" button up to N times |
| `link_pattern` | Regex for job links, when a site's URLs don't match the default shape |
| `list_selector` | CSS selector for each job card, if link-matching isn't working |

Jobs are found by **URL shape**, not CSS classes - class names on these sites
are build-generated (`css-1x9j2kf`) and change on every redeploy, while the
URL of a job detail page rarely does. `link_pattern` is the escape hatch when
a site's job URLs don't look job-shaped at all: Meta's are
`/profile/job_details/<id>` and TikTok's are `/search/<id>`, neither of which
any sane default would match.

**Cost:** a render now stops as soon as job-shaped links (or `list_selector`
cards) have appeared and stopped multiplying for 1.5s, and skips images, fonts
and video. It used to wait for the network to go quiet, which analytics-heavy
career sites never do, so most renders sat out the full 30s timeout plus 4s.
Rendering is still seconds per source versus milliseconds for a plain
request, which is why it's ordered last and why one Chromium process is shared
by every source in a round (then closed between rounds). With many rendered
sources a full sweep can exceed `poll_interval_seconds`; rounds then run
back-to-back, which is harmless, but see the timing note in `config/config.yaml`.

**What rendering still can't fix:**

- **Sites that block automated access outright.** `tesla.com` returns an
  Akamai "Access Denied" page to a headless browser before any JavaScript
  runs. That's a deliberate block, not a technical gap - working around it
  isn't something this tracker attempts.
- **Sites that never put jobs in the DOM.** Spotify's page renders, but its
  listings come from `api.lifeatspotify.com` and never become links, so
  there's nothing for a DOM scrape to find.
- **Intermittent throttling.** Some sites (Atlassian) serve the list fine on a
  first render but stop responding to rapid repeat ones. One render per source
  per round is normally fine; an occasional empty round for such a source is
  expected, not a bug.

If a rendered source finds nothing, the error message names the specific knobs
to try. Diagnose by dumping what actually rendered:

```bash
python -c "from tracker.sources import rendering; print(rendering.render('URL_HERE')[:3000])"
```

If `auto` picks the wrong thing, gets facts wrong (e.g. an Eightfold site
that only serves its API on a different host), or you already know the
platform, use one of the specific types below directly - they support finer
manual control (e.g. `api_host`, `ref_num`, `site_number` overrides) that
`auto` doesn't expose:

- **Apple** — Apple's careers site (jobs.apple.com) isn't on any of the ATS
  platforms below, and it's JavaScript-rendered, so plain scraping finds
  nothing there. This is why an `apple` source with 0 results doesn't mean
  no jobs exist - it means the scraper type needs to match the platform.
  Use `type: apple` (already set up in the default config) - it calls
  Apple's own internal search API directly. This is an unofficial,
  reverse-engineered endpoint, so if it ever starts erroring, Apple likely
  changed something; open jobs.apple.com in a browser, check the Network
  tab in dev tools for calls to `api/role/search`, and let me know what
  changed and I can update it.
- **Amazon** — `type: amazon` calls amazon.jobs' own search endpoint directly. Just set `query` (defaults to "intern").
- **Google** — Google's newer careers site is unusually scraper-friendly: it's server-rendered, so `type: google` with `careers_url` works via plain HTML parsing (matched on the URL pattern of job links, which is more stable than CSS classes). Note: this doesn't apply to Google's *old* careers.google.com/jobs site, which is JS-rendered.
- **Phenom People** — powers Cisco's careers site and others (look for `cdn.phenompeople.com` in image URLs as a tell). Use `type: phenom` with `domain` and `ref_num` (a per-company code, visible in job posting IDs and asset URLs on the page - Cisco's is `CISCISGLOBAL`).
- **Eightfold.ai** — another enterprise career-site platform (used by
  Applied Materials, American Express, and many others), including custom
  domains like `careers.company.com`. Use `type: eightfold` with
  `careers_url` set to the search page URL - the `domain` parameter is
  auto-extracted from its query string. If requests fail, the company's
  instance may only serve its API from a different host than the public
  page; set `api_host` manually in that case (check dev tools' Network tab
  for a request to `api/apply/v2/jobs` and copy its host).
- **Oracle Recruiting Cloud** — if a company's careers page is JS-rendered
  and `generic_html` returns nothing (a strong sign of this is a 0-result
  baseline, or requests failing with a 403), check whether they run on
  Oracle Recruiting Cloud - it powers not just Oracle's own site but many
  large companies (JPMorgan Chase, Goldman Sachs, Ford, Marriott, and
  others). Use `type: oracle_cloud` with `careers_url` set to the page you'd
  normally browse to - it auto-discovers the underlying API domain and site
  number. If auto-discovery fails (some instances redirect to the real API
  domain via client-side JS, which a simple script can't follow), open the
  careers page in a browser, open dev tools' Network tab, search for a job,
  find the request to `recruitingCEJobRequisitions`, and set `api_domain`
  and `site_number` manually in `config/companies.yaml` from that request.
- **Greenhouse** — if careers page is `boards.greenhouse.io/COMPANY` or embeds one, use `type: greenhouse`, `slug: COMPANY`.
- **Lever** — if it's `jobs.lever.co/COMPANY`, use `type: lever`, `slug: COMPANY`.
- **Workday** — if the URL looks like `company.wd5.myworkdayjobs.com/External`, use `type: workday` with `tenant`, `host` (the `wd5` part), and `site` (the `External` part).
- **Anything JavaScript-rendered** — `type: browser`, see the section above.
- **Everything else** — `type: generic_html` with a CSS selector pointing at each job link. Only for pages that render listings in plain HTML; if the jobs arrive via JavaScript, use `type: browser` instead.

Tip: to find a company's Greenhouse/Lever slug, open their "careers" page and
check the URL, or search `site:boards.greenhouse.io "company name"`.

## Notification channels

Two channels, and **both send one message per round, not one per posting.** A
sweep of ~1,100 companies can surface a dozen matches at once; a dozen separate
pings would be unusable. The per-job lines you see in the terminal are logging
only — they are not what gets sent.

| Round result | Email | ntfy push |
|---|---|---|
| Found matches | one digest listing all of them | one digest, high priority |
| Found nothing | **nothing sent** | quiet "round finished" heartbeat, low priority |

The digest is one list, most relevant first, two lines per posting:

```
Jane Street: Quantitative Trader Intern
https://boards.greenhouse.io/janestreet/jobs/...

Palantir: Forward Deployed Engineer Intern
https://jobs.ashbyhq.com/palantir/...
```

**Order.** `ranking.py` puts each posting in the first tier whose words appear
in its title: tier 1 is quant, data science, AI/ML and forward-deployed roles,
tier 2 is software, data engineering/analytics, research and security, and
tier 3 is everything else that passed the filters. Edit the words under
`ranking.tiers` in `config/config.yaml`, and set `ranking.send_tiers` to
`[1, 2]` to stop sending tier 3 at all.

**Duplicates.** The same posting found by several sources in one round is
listed once; career pages are checked first, so the link you get is the
company's own.

- **Email** — SMTP via Gmail. Address, recipient, and app password come from
  `.env` (`EMAIL_FROM_ADDRESS`, `EMAIL_TO_ADDRESS`, `EMAIL_APP_PASSWORD`), not
  from `config/config.yaml`, because that file is committed. Gmail
  authenticates as the sending account, so `EMAIL_FROM_ADDRESS` and the app
  password must belong to the same mailbox. Use an
  [app password](https://myaccount.google.com/apppasswords), entered without
  the spaces Google shows it with — a normal account password will not work.
- **Phone push (ntfy)** — the closest thing to an "Instagram notification."
  Instagram has no public API for sending yourself alerts and
  reverse-engineered approaches risk getting the account restricted, so this
  uses [ntfy.sh](https://ntfy.sh): free, no account. Install the app and
  subscribe to the exact topic string in `config/config.yaml`.

**Why the empty-round heartbeat exists:** without it, a tracker that crashed
three days ago looks identical to a quiet job market — in both cases your phone
just stays silent. The low-priority ping means silence is now a real signal
that something is wrong. Email deliberately doesn't do this; an inbox full of
"nothing today" defeats the point of an inbox.

SMS-via-carrier-gateway used to be a third channel and has been removed.

## Running it

Two modes:

```bash
.venv\Scripts\python.exe run.py
```

Loops forever, sweeping every `poll_interval_seconds`. Good for watching it
work; needs a terminal left open.

```bash
.venv\Scripts\python.exe run.py --once
```

One sweep, then exits. This is the mode to schedule. Exit code is `0` if the
round finished and `1` if it raised, so a scheduler's "last run result" means
something.

```bash
.venv\Scripts\python.exe run.py --once --skip-github
```

Career pages only, for a round where the GitHub half is in the way.

Either way it must be run **from the project root**, and it must be `run.py` —
the modules under `tracker/` are libraries, not entrypoints. Running one
directly (VS Code's plain "Run Python File" on an open file, say) fails with
`ModuleNotFoundError: No module named 'tracker'`, because Python then puts
`tracker/` on the import path instead of the project root. The configs in
`.vscode/launch.json` always do the right thing.

## How long a round takes

Measured on this machine, twice, with identical structure both times:

```
261 sources fetched concurrently, 10 at a time
 33 of those then rendered in a real browser, one at a time
262 ok, 6 errored, ~21,100 postings pulled
fetch wall clock: 15.4 min (while competing with a second sweep)
```

**That measurement predates the 2026-08-09 company sweep**, which took the list
from 261 sources to 1,104. The browser-rendered count didn't change (all 836 new
entries are API-backed boards), so the slow phase is the same size — but the
concurrent phase now has four times as much to get through. Re-measure before
trusting the number below.

**Budget 10–15 minutes** for a full round. The 33 rendered sources dominate:
Playwright's sync API isn't thread-safe, so renders can't be parallelized, and
on Windows ARM64 the Chromium build runs under x64 emulation, which isn't fast.
Raising `max_fetch_workers` will not help — the concurrent phase is already the
cheap part.

Every round now logs how long the HTTP phase and the browser phase took, and
the ten slowest sources - the place to look when a round runs long.

The first round after updating to the "record every posting as seen" change
writes every old posting the age filter used to hide into `seen_jobs.db` in
one go. It sends nothing for them and is a one-off.

If that ever needs to come down, the lever is the 33 rendered sources, not the
concurrency: converting `rendering.py` to Playwright's async API would let
several pages render at once and would cut the round to a few minutes. Nothing
else in the pipeline is close to being the bottleneck.

## Running it on a schedule (Windows Task Scheduler)

`run_once.bat` is the thing to schedule. It pins the venv interpreter, forces
the working directory to the project root, and appends output to
`data/logs/tracker-YYYY-MM.log`.

**1. Confirm the batch file works before scheduling it.** Double-click
`run_once.bat`, wait for it to finish, then check the newest file in
`data/logs/`. If that doesn't produce a log with a `=== Round finished ===`
line, scheduling it will only make the problem harder to see.

**2. Open Task Scheduler** — Start menu → "Task Scheduler" → **Create Task**
(not "Create Basic Task"; the basic wizard can't do three times a day).

**3. General tab**
- Name: `Internship Tracker`
- Leave **Run only when user is logged on** selected (the default).
- Tick **Run with highest privileges**.
- Configure for: **Windows 10** (also correct for 11).

On *Run whether user is logged on or not*: it sounds like the more robust
choice, and on this machine it isn't. It demands the account password, and this
account (`SUNNYS-SURFACE\lixin`) is a **Microsoft account** - so the password
is the Microsoft account password, not a local one, and it isn't the PIN or
Windows Hello used to sign in day to day. Worse, Task Scheduler caches that
credential and the cached copy silently breaks the next time the Microsoft
account password changes, leaving a task that appears configured and quietly
stops firing.

"Run only when user is logged on" needs no password and still runs with the
screen locked and the lid closed. The only case it misses is being fully signed
out or shut down - and a shut-down machine runs nothing under either setting.
If the laptop is genuinely off at the scheduled times, no Task Scheduler
configuration fixes that; see "Running it somewhere that's always on" below.

**4. Triggers tab** → **New**, three times, once per run. For each: *Daily*,
recurring every 1 day, with a different start time — e.g. `07:00`, `13:00`,
`19:00`. Under **Advanced settings** tick **Stop task if it runs longer than**
and pick `2 hours`, so a hung round can't overlap the next one. A healthy round
is 10–15 minutes (see below), so two hours only ever fires on a genuine hang.

**5. Actions tab** → **New**
- Action: **Start a program**
- Program/script: `C:\Users\lixin\portfolio\internship_tracker\run_once.bat`
- Start in: `C:\Users\lixin\portfolio\internship_tracker`

Fill in **Start in** even though the batch file also handles it. Leaving it
blank makes the working directory `C:\Windows\System32`, which is the single
most common reason a scheduled Python job fails.

**6. Conditions tab**
- Untick **Start the task only if the computer is on AC power** — otherwise it
  won't run on battery.
- Tick **Wake the computer to run this task**.
- Leave **Start only if the following network connection is available** unticked.

**7. Settings tab**
- Tick **Run task as soon as possible after a scheduled start is missed** —
  this is what covers a laptop that was asleep at 07:00.
- Untick **Stop the task if it runs longer than** only if you already set the
  per-trigger limit in step 4; one limit is enough.
- If the task is already running: **Do not start a new instance**.

**8. Save.** With "Run only when user is logged on" there's no password prompt.

**9. Test it.** Right-click the task → **Run**. Then check:
- Task Scheduler's **Last Run Result** should read `The operation completed
  successfully (0x0)`
- A fresh log should appear in `data/logs/`
- You should get an ntfy push — a digest if anything was found, a quiet
  "round finished" heartbeat if not

That heartbeat is the whole point of unattended operation: three pings a day
means it's alive, and silence means something needs looking at.

**A sleeping laptop is the main failure mode.** "Wake the computer to run this
task" only works from sleep, not from hibernate or shutdown. If the machine is
regularly off at those hours, either pick times when it's awake or move the
tracker to something always-on — a free-tier VM with `cron`, or a scheduled
GitHub Actions workflow.

## Resetting a company's tracked history

If you fix a broken source config, or just want a company's tracking to
start over, list its name in `config/companies_to_reset.txt` (must match the
`name` field in `config/companies.yaml` exactly) and run:

```bash
.venv\Scripts\python.exe -m scripts.reset_companies
```

This wipes that company's stored job records and baseline flag, so the next
check re-baselines it from scratch - existing postings won't trigger
notifications, only new ones from that point on. It does **not** touch
`config/companies.yaml` or stop monitoring the company - to do that, remove its
entry from `config/companies.yaml` directly. The reset file clears itself after each run.

## Checking job counts on demand

```bash
.venv\Scripts\python.exe -m scripts.stats
```

Prints total jobs recorded per company without starting the full loop.

## Finding broken scrapers

```bash
.venv\Scripts\python.exe -m scripts.health_check
```

Does one fresh fetch per source and reports any that used to return jobs but
now return zero — almost always a sign the scraper broke (a site redesign, a
moved slug, a new block) rather than the company genuinely having no openings.
Writes nothing and sends nothing, so it's safe to Ctrl+C partway through. Takes
a while, since browser-rendered sources cost ~10s each.

All three scripts are run as modules from the project root, which is what puts
the `tracker` package on the import path.

## Project layout

```
run.py                      the entrypoint; --once for a single sweep
run_github_boards.py        the GitHub half on its own, for adding/debugging a repo
run_once.bat                what Windows Task Scheduler runs
dedupe.py                   one posting, one line, however many sources carried it
requirements.txt
.env                        secrets, never committed (.env.example is the template)

config/
  companies.yaml            the company list; the file you'll keep adding to
  config.yaml               keywords, filters, notifications, poll interval
  companies_to_reset.txt    scratch input for scripts/reset_companies
  github_boards.yaml        the 51 GitHub lists + their own filter settings

tracker/
  paths.py                  where everything lives on disk - the only module
                            that knows the directory layout
  config.py                 reads the two YAML files into one settings dict
  pipeline.py               one polling round: fetch, filter, classify, notify
  state.py                  SQLite dedupe store + per-source baseline flags
  classifier.py             the LLM double-check for near-miss postings
  notifiers.py              email digest + ntfy push, one message per round

  filters/
    location.py             best-effort US/Canada classification
    degree.py               excludes explicitly Masters/PhD-only postings

  sources/
    __init__.py             the FETCHERS registry + fetch_all_jobs
    common.py               HTTP settings, date parsers, URL helpers
    boards.py               Greenhouse, Lever, Ashby, Workday - real JSON APIs
    enterprise.py           Apple, Amazon, Google, Oracle, Eightfold, Phenom
    extract.py              heuristic "find the job links" HTML scrape
    detect.py               working out which platform a URL is on
    generic.py              generic_html, browser, and the `auto` chain
    rendering.py            headless Chromium (optional; needs Playwright)

scripts/
  stats.py                  job counts per company, no loop required
  health_check.py           which scrapers look broken
  reset_companies.py        wipe a company's tracked history

github_boards/              the GitHub-repo half; see docs/GITHUB_BOARDS.md
  config.py                 reads config/github_boards.yaml
  fetch.py                  raw.githubusercontent + the trees API, ETag-cached
  parse_json.py             listings.json style files
  parse_markdown.py         GitHub tables, whatever their column layout
  parse_yaml_dir.py         one-YAML-file-per-company repos
  normalize.py              cell cleaning, date parsing, stable job ids
  relevance.py              the filters a repo posting has to survive
  state.py                  github_jobs.db - seen postings, baselines, ETags
  notifiers.py              how a GitHub posting reads in the digest
  pipeline.py               one GitHub round

data/
  seen_jobs.db              dedupe + baseline state, created automatically
  github_jobs.db            the same, for the GitHub half
  logs/                     output from scheduled runs, one file per month
  scratch/                  one-off outputs from company-discovery sweeps

docs/
  CANDIDATE_PROFILE.md      who this tracker is filtering for
  GITHUB_BOARDS.md          the GitHub half: repos, parsing, duplicates
```

**Adding a new job-board platform:** write a `fetch_*` function in the right
`sources/` module (`boards.py` if it has a real API, `enterprise.py` if it's a
bespoke company endpoint), then add one line to `FETCHERS` in
`sources/__init__.py`. Nothing else needs to know it exists.

## Notes / limitations

- Respect each site's terms of service and `robots.txt` — this script only
  hits public job-listing pages/APIs at a modest interval, similar to a
  human refreshing the page.
- `generic_html` and the `auto` fallback scrape are fragile — if a company
  redesigns their site, the selector/link pattern may need updating.
- The AI double-check is free via Groq's free tier. If you ever hit their
  rate limits (unlikely at this volume), set `ai_classification.enabled: false`
  in `config/config.yaml` to fall back to keyword-only matching.
