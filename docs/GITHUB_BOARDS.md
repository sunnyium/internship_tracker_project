# GitHub Job-Board Watcher

A second tracker that watches 51 crowdsourced internship lists kept in GitHub
repositories, instead of company career pages. New postings arrive by email and
ntfy push, one digest per round.

**It runs as part of `run.py`.** A round sweeps the career pages first, then the
GitHub repos, and sends one message covering both, career-page results first.
`run_once.bat` and the scheduled task need no changes to pick it up. Everything
below is about the GitHub half specifically; `run_github_boards.py` still runs
that half on its own, which is what to use while adding or debugging a repo.

```bash
.venv\Scripts\python.exe run_github_boards.py --dry-run
```

```bash
.venv\Scripts\python.exe run_github_boards.py --once
```

The two halves keep separate databases (`data/seen_jobs.db` and
`data/github_jobs.db`), so resetting one leaves the other alone.

## Why these repositories

Chosen against `docs/CANDIDATE_PROFILE.md`: undergraduate, Summer 2027, US and
Canada, AI/ML first, then data science and analytics, then quant and finance,
with Canadian programs counted as a specific plus. Star counts and last-push
dates were checked on 2026-08-09; anything last touched before 2026 was left
out, because a stale list generates no new postings and costs a fetch every
round.

Every repo in the config was fetched and parsed before it was added. A list
that looks perfect and yields zero rows is worse than not having it, because it
shows up as a quiet repo rather than as an error.

**Overall lists (21).** Broad US coverage, every field. `SimplifyJobs` and
`vanshb03` are the reference lists for the cycle and the only two that publish a
machine-readable file with an `active` flag and real timestamps. Around them sit
the daily-updated scrapers - `speedyapply`, `zapplyjobs`, `zshah101`,
`forgeapply`, `ApplyGuy`, `dreamworkhq`, `tailed-community`, `DereC4`,
`SuryaHarikrishnan`, `aprameyak`, `Chieler`, `Emjumaev` (big tech only),
`jerrylin-23` (North America), `dubiels` (off-season), plus regional and
smaller curated lists (`ctsc` for the southeast, `kazisean` for NYC,
`resumax`, `Edamame-Labs`, `michae1lm`, `summer2026internships`). The largest,
`IEEEAtCornell/2026-ECE-Internships`, carries about 17,000 rows on its own.

**Field-specific (8).** `speedyapply/2027-AI-College-Jobs` is lane 1 and runs
with the keyword filter off, since every row in it is already AI/ML. The seven
`jobright-ai` lists cover data analysis, software, business analyst,
engineering, accounting and finance, consulting and product.
`northwesternfintech/2027QuantInternships` is where trading firms appear first.

**Canada (12).** A specific plus in the profile, not a fallback, so it gets its
own block rather than being left to the US lists to mention in passing:
`negarprh`, `zapplyjobs/Canada-Internships-2027`, `Francklin9999`, `Krishpraj`,
two from `hanzili`, `Dannny-Babs`, `jenndryden`, `lucianlavric`,
`MubeenMohammed`, `isaiahiruoha` (tech *and* business, and the one list that
tags roles by year - "Sophomore Summer Business Analyst" is a row in it) and
`SamZhang02`.

**Underclassmen (3).** Summer 2027 is the sophomore summer, which is the year
the big lists implicitly skip - their rows assume a penultimate-year student.
`zapplyjobs/underclassmen-internships`,
`Jose-Gael-Cruz-Lopez/underclassmen-opportunities` and `LuisaE/opportunities`
exist for the year below that. All three run with both filters off, because
their rows are program names rather than role titles.

**Programs and batch schemes (3).** Fixed cohorts and deadlines rather than
rolling postings, where the event worth catching is a program opening at all:
`deepanshu1422/List-Of-Open-Source-Internships-Programs` (GSoC, MLH,
Outreachy), `Julian048/CS-Everything-but-Internships`, and
`LogicodeHQ/hardware-jobs-internships-2026`.

Things considered and left out: `paralax/awesome-cybersecurity-internships` and
`zapplyjobs/Research-Internships-for-Undergraduates` write their listings as
prose or bullets rather than tables, so nothing parses out of them;
`workopia/*` publishes rows with no application URL at all, which leaves
nothing to open and nothing stable to identify a posting by; and every
new-grad-only list (`SimplifyJobs/New-Grad-Positions` and friends) is for a
graduating class Sunny is three years away from.

## How a round works

1. Read every repo, four at a time. Files come from `raw.githubusercontent.com`,
   which is outside GitHub's API rate limit.
2. Parse each file according to its repo's `strategy`.
3. Drop postings older than `max_posting_age_days` where the list publishes a
   date. Undated rows are kept.
4. On the first successful read of a repo, record everything it currently lists
   as a baseline and notify for none of it. Only postings that appear after
   that point ever fire an alert.
5. Judge everything new (see Filters).
6. Send one email and one push covering the whole round.

State lives in `data/github_jobs.db`: seen postings, which repos have been
baselined, and one ETag per file.

**The ETag cache is what keeps this cheap.** The Simplify listings file is 10MB
and changes a few times a day. Every fetch sends the ETag from the last
successful read, so most rounds get a 304 with an empty body and the repo is
skipped without parsing 14,000 entries to discover the same thing. `--dry-run`
bypasses the cache on purpose, so it always re-reads everything.

Measured on this machine, over all 14 repos:

```
cold cache, every file downloaded and parsed    90 s
warm cache, every file answered 304             14 s
```

A realistic scheduled round sits between the two, since a handful of the lists
will have changed. Either number is short enough to schedule hourly, although
these lists update daily rather than continuously, so three times a day is
plenty.

## Repository structures it handles

There is no standard for this. Each list invents its own layout, and the
strategies exist because of specific things the real repos do.

**`json`** reads a `listings.json` file: the Simplify schema and the forks of
it. Field names are matched through aliases, so a fork that renames
`company_name` to `company` still parses. Entries with `active: false` or
`is_visible: false` are skipped.

**`markdown`** reads GitHub-flavoured tables out of `.md` files. Columns are
matched by header name against a synonym table rather than by position, because
the five layouts in use here head their columns:

```
Company | Position | Location | Salary | Posting | Age
Company | Job Title | Location | Work Model | Date Posted
Company | Role | Location | Apply | Added
Company | Role | Category | Location | Skills | Posted | Apply
Name    | Status/Open Date | Year | Note
```

Inside a cell it copes with `**[Citadel](https://citadel.com)**`,
`<a href="..."><strong>TikTok</strong></a>`, a bare company name, and the
common case of an apply link written as a shields.io badge image wrapped in the
link that actually matters. Badge and icon URLs are discarded; the destination
is kept.

Two conventions are load bearing. A company cell holding an arrow means "same
company as the row above", which every one of these lists uses to write a run
of roles at one employer once; missing it attributes every follow-on row to
nobody. And a locked or struck-out apply cell means the role has closed, which
is the only "this is gone" signal a markdown list carries.

Tables that are not job tables are skipped rather than guessed at. A table
qualifies only if it has a company or role column plus at least one of role,
link, location, date or status, which is what keeps navigation tables and
"here are some other repos" link tables out of the digest.

**`yaml_dir`** reads a repo that keeps one YAML file per company, which is how
the quant list is built: `data/jane-street.yaml`, `data/citadel.yaml`, and 56
more, each naming the firm once and listing role links under short role codes.
One tree call finds the files, then each is read directly. That layout carries
no dates at all, so every posting from it is undated and the database is the
only thing preventing repeat notifications.

**`auto`** tries the known JSON paths first and falls back to the README. Use it
when adding a repo whose layout you have not looked at yet.

## Filters

In order, cheapest and most certain first:

1. **Citizenship and clearance.** A posting stating a US-citizenship
   requirement or an active clearance is dropped. This is the one filter here
   that fails closed, because it is the one binary constraint in the profile.
2. **Location.** Confidently outside the US and Canada, dropped. Unknown or
   unparseable locations are kept.
3. **Degree.** Explicitly Masters/PhD-only postings are dropped. "BS/MS" and
   "PhD preferred" are kept.
4. **Title.** Must look like an internship, co-op, student or summer analyst
   role. Turn off per repo with `require_internship_title: false`.
5. **Keywords.** The fields of interest, listed in `config/github_boards.yaml`.
   Turn off per repo with `keyword_match: false`.

Steps 2 and 3 reuse `tracker/filters/`, which are pure functions with no config
or state behind them. That is the only thing the two halves of the project
share.

There is no LLM step. The career-page tracker asks a model about postings that
pass the title check but miss every keyword, and it decides using the job
description. These lists carry no descriptions, so a model would be judging a
title that the keyword pass has already judged. Where a whole list is on-topic
the right answer is to turn the keyword filter off for that repo, which is what
`keyword_match: false` does for the AI, quant and underclassmen lists.

## Notifications and duplicates

Two channels, both firing once per round, never once per posting.

| Round result | Email | ntfy push |
|---|---|---|
| Found matches | one digest, grouped by repo | one digest, high priority |
| Found nothing | nothing sent | quiet "round finished" heartbeat, low priority |

Run through `run.py`, the message covers both halves as one list, most
relevant first (see `ranking.py` and `ranking` in `config/config.yaml`):

```
Jane Street: Quantitative Trader Intern
https://...

Stripe: Data Scientist Intern
https://...
```

**Repeats are the price of fifty overlapping lists.** One Greenhouse posting
gets scraped from the company's own careers page, crowdsourced into Simplify,
mirrored into three smaller lists, and rewritten by jobright behind a tracking
URL. Within a round `dedupe.py` keeps the first copy. Across rounds
`seen_index.py` remembers every posting either half has examined, by link
(tracking parameters stripped), by job number, and by company + title, so a job
that reaches a second list a day later is recognized and not sent again.

First place wins, and order is deliberate: career pages before GitHub lists,
then GitHub lists in the order `github_boards.yaml` lists them. A link from the
company's own posting is the one worth opening.

Running the GitHub half on its own, push titles start with `GitHub boards`, so
it is obvious on a lock screen which command sent the message. The ntfy topic in
`config/github_boards.yaml` is deliberately the same one the career-page
tracker uses, so one subscription covers everything.

ntfy refuses a message body over 4KB. A round that surfaces sixty postings
would exceed that and the push would silently never arrive, so the push body is
trimmed to whole postings and ends with a count of what did not fit. The email
always carries everything.

Email credentials come from `.env` (`EMAIL_FROM_ADDRESS`, `EMAIL_APP_PASSWORD`,
`EMAIL_TO_ADDRESS`), the same three the career-page tracker reads. Nothing extra
to configure.

## Running it

| Command | What it does |
|---|---|
| `run_github_boards.py --dry-run` | Re-reads every repo ignoring the ETag cache, prints the digest that would have gone out, writes nothing and sends nothing |
| `run_github_boards.py --once` | One round, then exit. This is the mode to schedule. Exit code 0 if it finished, 1 if it raised |
| `run_github_boards.py` | Loops forever, sleeping between rounds |
| `run_github_boards.py --repo quant` | Restricts the round to repos whose name or `owner/name` contains that string |
| `run_github_boards.py --stats` | Postings recorded per repo, no fetching |
| `run_github_boards.py --reset "NUFT Quant 2027"` | Forgets one repo, so the next round re-baselines it from scratch |

Run it from the project root, and use `--dry-run` after every config edit: a
misconfigured repo that runs for real will baseline itself into silence before
you have seen a line of its output.

`GITHUB_TOKEN` in `.env` is optional. Only the `yaml_dir` strategy touches the
REST API, and the unauthenticated limit of 60 calls an hour covers one such
repo comfortably. Add a token before configuring several more.

## Adding a repository

Append to `repos` in `config/github_boards.yaml`, then dry-run it:

```yaml
  - name: "Some List"
    repo: "owner/name"
    strategy: auto
```

```bash
.venv\Scripts\python.exe run_github_boards.py --dry-run --repo "Some List"
```

If it reports `parsed 0 rows`, the file was fetched and nothing job-shaped came
out of it. Look at the actual table headers and either add the header names to
`COLUMN_ALIASES` in `github_boards/parse_markdown.py` or point `paths` at the
right file.

## When it breaks

These lists are maintained by strangers and change without notice. Three
failure shapes, and how each looks in the log:

- **`Fetch failed, skipping this round`** with a 404: the repo was renamed,
  archived, or rolled over to a new year. Look it up and update `repo`. The
  Summer 2027 lists will become Summer 2028 lists at some point in 2027.
- **`parsed 0 rows, the layout may have changed`**: the file is still there and
  the table is not. Usually a new column layout.
- **A repo that quietly stops producing new postings** while others keep going:
  the list was abandoned. `--stats` shows how much each repo has ever
  contributed, which is the fastest way to spot one.

## How it is wired into the rest of the project

`run.py` owns the round:

```
run_once.bat  ->  run.py --once  ->  career-page sweep   (tracker/)
                                 ->  GitHub repo sweep   (github_boards/)
                                 ->  dedupe across both  (dedupe.py)
                                 ->  one email + one push
```

`tracker/pipeline.run_once` and `github_boards/pipeline.run_once` both take
`notify=False` when run this way and return their matches instead of sending;
`run.py` assembles the sections and `tracker/notifiers.notify_sections` sends
the one message. Each half is wrapped separately, so a GitHub failure still
delivers the career-page results and vice versa - the log names which half
raised and the round exits 1.

`--skip-github` turns this half off for one run without touching any config.

`data/github_jobs.db` is per-machine notification history, like
`data/seen_jobs.db`, and the `*.db` rule in `.gitignore` keeps both out of git.
