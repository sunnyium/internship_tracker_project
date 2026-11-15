# Candidate Profile — Sunny Li

Everything needed to make a company or role recommendation without re-asking.
Written 2026-08-08 for the **Summer 2027** cycle. Companion to `companies.yaml`
and `config.yaml` — this file says *who the filters are for*.

---

## 1. Hard constraints

These are binary. A role failing any of them is not a recommendation.

| Constraint | Value |
|---|---|
| Term | Summer 2027 (May–Aug) |
| Level | Undergraduate. Bachelor's-eligible only |
| Geography | United States and Canada |
| Work authorization | Canadian citizen, F-1 student at UChicago |
| US internships | **Open** — CPT-eligible, no employer sponsorship needed |
| US post-graduation | **Low friction** — TN status, no H-1B lottery |
| Canadian roles | No restriction |
| Auto-reject | Requires US citizenship or an active security clearance |

**The sponsorship question is the one most often gotten wrong.** Sunny needs
nothing from a US employer to intern there in Summer 2027. Any recommendation
logic that discounts US companies on visa grounds is wrong.

---

## 2. Who this is

**Sunny Li** — University of Chicago, entering sophomore year (started Sep 2025).
B.S. Data Science + B.S. Computational and Applied Mathematics, Minor in
Computer Science. GPA 3.8. Home base Edmonton, AB; term-time Chicago, IL.

Davis UWC Scholar, President's Scholar, Kappa Eta Kappa. IB 43, SAT 1550, from
United World College USA.

⚠️ **Graduation year is unconfirmed and it matters.** Sep 2025 start implies
Class of 2029, which makes Summer 2027 the *sophomore* summer — one year before
the penultimate-year summer that bank Summer Analyst programs are built for.
Resolve this before recommending anything in the banking lane. (See §8.)

---

## 3. What Sunny wants

**Lanes, ranked:**

1. AI/ML engineering or applied ML research
2. Data science / analytics
3. Quant / finance — *opportunistic only*, no quant-specific materials exist
4. Anything else the resume plausibly matches

Software engineering is in scope but explicitly **not a priority**. Keep the
`software engineer` keywords in `config.yaml`; don't optimize for the lane.

**Employer profile:** large and well known. Brand recognition is the dominant
axis. Structured internship programs preferred. Canadian internship programs
are a specific plus, not a fallback. Also open to AI-native startups, big tech,
banks/fintech/exchanges, and mid-size product companies — but the brand
constraint cuts across all of these.

**An AI/ML component is wanted where the role allows it**, without restricting
to pure ML roles.

**Location:** anywhere with a good role. Toronto, NYC, Bay Area, Seattle,
Chicago, and Edmonton/Calgary/Vancouver are all live.

**Compensation:** no floor. Brand and learning outrank pay.

**Exclusions:**
- Categorically drop employers who cannot hire non-US citizens at all
- Northrop Grumman and Booz Allen Hamilton — mostly cleared work, ineligible
- Palantir — a stated preference against, *not* an eligibility bar (their
  commercial roles do hire non-citizens). Keep scraping; rank last

**There is no fallback.** Sunny is not pursuing a Frontier Technology Institute
return offer. Something must land.

---

## 4. What the record actually proves

Recommendations should be grounded in demonstrated evidence, not the skills
list. Sorted by strength.

**Well evidenced — lead with these**

| Capability | Evidence |
|---|---|
| Large-scale data wrangling | 60M EMS responses in Polars; 2.5M-flow parquet via chunked PyArrow with bounded peak memory |
| Applied statistical modeling | Survival analysis, per-protocol logarithmic curve fitting, OR 1.09 mortality per response-minute |
| Supervised ML with honest evaluation | 7-class XGBoost, 0.965 macro-F1, then diagnosed the macro-precision gap to one class at 1,064:1 imbalance |
| SQL / PostgreSQL | Daily and aggregate queries across 1,000-student datasets |
| R and regression | Multivariate regression on 7 RCT cohorts, 163 participants |
| LLM / RAG application building | n8n + Supabase pgvector with metadata filtering and structured output schemas; 96% of pilot responses met quality criteria |
| Research data ethics | HIPAA/IRB protocols, de-identified records, subgroup-size checks before demographic reporting |
| Geospatial analysis | Chicago crime × education regressions, CRS standardization across a 4-person team |
| Shipping to real users | Darkhorse work integrated into dashboards in 50+ North American cities |

**Listed on the resume but thinly evidenced — do not lead with these**

- **A/B testing** — appears under Statistical Methods on three resume versions,
  but no bullet anywhere demonstrates it. This is the single most-asked topic
  in product data science interviews. Treat product-DS roles at consumer tech
  as a stretch until this is real.
- **PyTorch / computer vision** — one in-progress project (Faster R-CNN on
  BDD100K). Honest, but not yet a completed result.
- **AWS, Docker, MLflow, Spark** — listed; no bullet shows them in use.
- **No ML coursework at all.** Confirmed by Sunny. The ML capability is
  entirely experience-derived. This is the binding constraint on the top lane.

**Non-technical strengths that are unusually strong for a sophomore**

Founded EduCamp — 12+ camps, 500+ students, 3 Canadian cities, $10K budget,
recognized by the Alberta Minister of Education. Two publications in
preparation, three posters including SGIM Annual Meeting. Bilingual English /
Mandarin.

---

## 5. Recommendation heuristics

**Rank a role UP when it has:**
- A recognizable employer name with a named, structured intern program
- A Canadian office that actually hosts interns
- Applied ML, data science, or analytics on real production data
- An "ambiguous problem, own it end to end" flavor — this matches both the
  strongest cover-letter material and the actual work history
- A regulated or high-stakes data domain (health, finance, safety, compliance).
  The Volerman and Darkhorse experience is a genuine differentiator here, and
  the KPMG letters show Sunny already knows how to argue it

**Rank a role DOWN when it requires:**
- ML *research* with a publication record or graduate coursework — no ML
  courses on the transcript
- Heavy systems/C++/infrastructure engineering
- Quant trading with stochastic calculus or derivatives pricing
- Deep product A/B testing and experimentation ownership
- Prior internship at a peer-tier company as a stated bar (this is the
  sophomore-year reality, not a fixable gap)

**Auto-reject:** clearance or US-citizen-only; Masters/PhD-only; outside US/CA;
not an internship. `degree_filter.py` and `location_filter.py` already handle
the last three, both fail-open by design.

---

## 6. Materials on hand

Five resume versions. Sunny sends all of them, mostly DS and AI.

| Version | Use for |
|---|---|
| TECHNICAL DS | Data science, analytics, research |
| TECHNICAL AI | ML/AI engineering (differs from DS by ~one line — merge candidate) |
| BUSINESS/FINANCE | Banking, consulting, business analytics |
| LEADERSHIP + TECHNICAL | Roles weighting leadership and program impact |
| CUSTOMER SERVICE | Non-technical fallback |

⚠️ **BUSINESS/FINANCE lists a different degree** — "B.S. in Economics with Data
Science Concentration" where the other four list "B.S. in Data Science; Minor
in Computer Science." UChicago's Economics is a B.A. Unresolved.

Other inconsistencies to fix before the next send: Frontier is dated May–Aug
2026 (i.e. currently ending) but a cover-letter paragraph calls it "last
summer"; Polsky carries two different job titles; Data Science Society ends
"Jun 2026" on one version and "Present" on three.

**No resume version has a relevant-coursework section.** Unusual for a
sophomore and probably costing something.

**Cover letter kit:** a slot-marked template, four reusable body paragraphs
(Frontier / Darkhorse / Volerman / Polsky), and seven interchangeable "Beyond
the technical work itself…" closers keyed to different company values —
ownership, continuous learning, cross-functional collaboration, real-world
impact, ill-defined problems, and diverse teams.

Two fully written letters exist as quality benchmarks: **KPMG Forensic
Financial Crimes** and **KPMG Technology Risk Services**. Both are strong. Both
leave the `[After speaking with NAME]` slot empty.

---

## 7. Current state of the search

**Submitted:** Morgan Stanley, JP Morgan, Microsoft, Micron, KPMG — all
Summer Analyst / summer intern, not sophomore insight programs.

**Read the spread honestly.** Five applications, all large-institution
finance / big tech / Big 4. Nothing from the ~130-company AI and data long tail
the tracker was specifically built to surface. Revealed preference so far is
*brand-name structured program*, which diverges from the stated #1 lane of
AI/ML. Recommendations should serve the stated preference but flag the gap.

**No referrals anywhere.** With no network, the GitHub at
`github.com/sunnyium` carries the weight for AI-native companies. It is
populated but not audited — the CIC-IDS2017 project with its precision analysis
is the strongest single asset for that audience and should be the profile's
front door.

**Channels:** the scraper covers ~260 employers on a 24-hour window with
10-minute polling. UChicago Handshake, Metcalf, and Career Advancement run in
parallel and deliberately outside the scraper's reach.

**Strategy is undecided** — high-volume light-tailoring vs. a two-tier approach
(bulk apply, plus ~20 hand-written at KPMG-letter quality). Unresolved.

---

## 8. Open questions that would sharpen recommendations

1. **Graduation year.** 2029 or an accelerated 2028? Determines whether bank
   Summer Analyst eligibility holds for 2027. Highest-value unknown here.
2. **Fall 2026 and Winter 2027 coursework.** A single machine learning or
   probability course changes what's defensible in the top lane.
3. **Is Economics actually a declared major**, or is the BUSINESS/FINANCE
   header aspirational?
4. **Philip Morris International** is in `companies.yaml` and was never ruled
   in or out.
5. **Weekly hours available for applications** during term. Decides the
   volume-vs-depth question in §7.
6. **Which ~20 companies earn a hand-written letter**, once the target list
   exists.
