# Beacon Signal — Claude Code Instructions

## What This Is

Beacon Signal is a rep signal prioritization engine. It ingests multi-source
account signals (job changes, intent data, engagement, funding, CRM activity),
applies a configurable weighted scoring model with time decay and velocity
tracking, and outputs a prioritized account list with plain-English reasoning
for every score.

**One-line problem statement:** Every company has 5 signal sources and no
prioritization framework. Beacon Signal is the middleware that answers
"who do I call first?"

This is a portfolio project built by Henry Marble as part of a career pivot
from SDR to GTM Engineer. Do not reference Pave as a current employer or
accessible resource.

## Tech Stack

- **Signal ingestion:** Python, adapter pattern (one adapter per source)
- **Scoring engine:** Python, Pandas, NumPy
- **Database:** Supabase (PostgreSQL) — shared instance, `signal` schema
- **LLM layer:** Claude API (`claude-sonnet-4-6`)
- **MCP server:** FastMCP (Python)
- **Dashboard:** Next.js, TypeScript (Phase 5)
- **Alert delivery:** Slack bot (Socket Mode), Slack SDK
- **Deployment:** Railway (pipeline + MCP server + Slack bot), Vercel (dashboard)
- **Config:** YAML for weights, thresholds, decay parameters

## Repo Structure

```
pipeline/
  adapters/           # One adapter per signal source (5 types)
    base.py           # BaseAdapter class + SignalEvent model
    job_change.py     # Champion hired, economic buyer change, champion departed
    intent_surge.py   # Category research, competitor research
    engagement.py     # Pricing page visits, demo requests, content downloads
    funding_growth.py # New funding rounds, headcount growth
    crm_activity.py   # Last activity, open opportunities, sequence enrollment
  scorer.py           # Weighted scoring engine with time decay + velocity
  decay.py            # Time decay utilities (reused by MCP + dashboard)
  config.py           # Config loader for YAML files

alerts/
  engine.py           # Alert evaluation — checks scores against thresholds (Phase 4)

server/
  server.py           # FastMCP server for Claude Desktop (Phase 3)

config/
  weights.yaml        # Signal weights, time decay half-lives, velocity settings
  alert_thresholds.yaml  # Alert tier definitions (CRITICAL/HIGH/STANDARD)

data/
  synthetic/          # Copied from beacon-data/output/ — never generated here
  mock_signals.json   # Legacy placeholder — being replaced by synthetic/

migrations/
  001_signal_schema.sql  # Supabase schema (signal schema, not public)

dashboard/            # Next.js frontend (Phase 5)
```

## Before You Write Any Code

1. **Read this file first.** Every session starts here.
2. **Read the files you are about to edit** — do not assume you know what is there.
3. **Check `config/weights.yaml`** before changing scoring behavior.
4. **Check `migrations/`** before writing any SQL.

## planning-with-files — Required Protocol

Maintain three files in the repo root at all times during multi-step work:

- `findings.md` — what you discovered when reading existing code, files,
  schemas, or data. Write before touching anything.
- `progress.md` — step-by-step status: Not Started / In Progress / Done /
  Blocked. Update after every step.
- `task_plan.md` — full task list with step numbers and current status.
  Update after every step.

### Rules
1. Initialize all three files before writing any code. No exceptions.
2. Update all three after each step — not at the end of the session.
3. If blocked, record the blocker in progress.md immediately and stop.
4. Final update to all three files at session end.

These files are gitignored. They are your working memory. Skipping them is
not allowed.

## Hard Rules — Things CC Gets Wrong

### Data

- **All data is synthetic.** No real company data anywhere. Do not attempt
  to connect to real APIs or orgs.
- **beacon-data is the source of truth for all synthetic data.** Signal does
  NOT generate its own mock data. It copies from `beacon-data/output/` into
  `data/synthetic/`. See "Synthetic Data" section below.
- **Do NOT modify any files in beacon-data or beacon-loop.** Read from them
  for schema reference only.
- **`DEMO_MODE=true`** means read from `data/synthetic/`. This is the default
  and the only mode that works until live integrations are built.

### Database

- **Schema is `signal`, not `public`.** Loop owns `public`. All Signal tables
  go in the `signal` schema. Always prefix table names with `signal.` in queries.
- **Supabase project ID:** `qzeehftbbvccqoqdpoey` (shared with Loop).
- **No per-user RLS.** Service role key only.
- **Always destructure and check errors** on every Supabase call.

### Scoring

- **Every score is explainable.** `score_breakdown` is written at scoring time,
  not generated after the fact. This is the core design principle.
- **score_breakdown is the score.** The `final_score` is just the sum of the
  breakdown components. If breakdown and final_score disagree, the breakdown
  is wrong.
- **Weights come from `config/weights.yaml`.** Do not hardcode weights in
  scoring logic.
- **Time decay is exponential.** `decay_factor = 0.5 ^ (age_days / half_life_days)`.
  Half-lives are configurable per signal category in `weights.yaml`.
- **Velocity bonus is multiplicative.** When enough signals accumulate within
  the velocity window, the base score is multiplied by `bonus_multiplier`.

### Adapters

- **One adapter per signal source.** Each adapter owns specific signal types
  and is responsible for writing `reason_text` (the human-readable explanation).
- **All adapters implement the same interface.** The scoring engine doesn't
  know or care where signals come from.
- **In demo mode, all adapters read from `data/synthetic/signal_events.json`.**
  In production (future), adapters call external APIs. The adapter interface
  is the same either way.

### MCP Server

- **Five tools:** `get_prioritized_accounts`, `get_account_signals`,
  `get_score_breakdown`, `configure_weights`, `get_signal_decay`.
- **LLM model is `claude-sonnet-4-6`.** Do not substitute another model.

### Alerts

- **Alerts are part of Signal, not a separate module.** They live under `alerts/`.
- **Three tiers:** CRITICAL (real-time Slack DM + MCP push), HIGH (real-time
  Slack DM), STANDARD (morning digest).
- **Every alert includes score breakdown.** No alert fires with just a number.
- **Max 3 real-time alerts per rep per day** (org-level default, configurable).

### Secrets

- `SUPABASE_SERVICE_KEY` is server-side only. Never expose in dashboard
  client-side code.
- `ANTHROPIC_API_KEY` is server-side only.
- `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are server-side only.

## Synthetic Data

All synthetic data originates from `beacon-data` at `C:\Dev\beacon-data`.

### Consumer pattern
```bash
# Copy beacon-data output into Signal
cp ../beacon-data/output/*.json data/synthetic/
cp ../beacon-data/output/*.csv data/synthetic/
```

### Key files consumed
| File | Records | Use |
|---|---|---|
| `signal_events.json` | ~5987 | Signal events with weight + reason_text |
| `score_history.json` | ~3017 | Pre-computed weekly score snapshots |
| `tribal_patterns.json` | 7 | Pattern definitions with conversion rates |
| `account_preferences.json` | 25 | Snooze/override records |
| `alert_log.json` | ~1394 | Pre-generated alerts across tiers |
| `sf_accounts.csv` | 500 | Accounts (T1: 25, T2: 75, T3: 400) |
| `sf_contacts.csv` | ~247 | Contacts at target accounts |
| `sf_opportunities.csv` | ~208 | Opportunities with stages and owners |
| `reps.json` | 19 | SDRs, AEs, managers (all @doom.com) |

### ID conventions
- Accounts: `sf_acc_001` through `sf_acc_500`
- Reps: `sdr_1`–`sdr_6`, `ae_1`–`ae_10`, `mgr_1`–`mgr_3`
- Opportunities: `sf_opp_001`+
- Signal events: `sig_00001`+
- Score history: `sh_00001`+
- Tribal patterns: `tp_001`–`tp_007`

### beacon-data signal types
These are the signal types generated by beacon-data. Adapters must map
these to Signal's internal types:

| beacon-data type | Weight | Source |
|---|---|---|
| `pricing_page_visit` | 15 | web_analytics |
| `job_change` | 20 | linkedin |
| `intent_surge` | 10 | bombora |
| `web_visit` | 5 | web_analytics |
| `competitor_mention` | 12 | g2_reviews |
| `funding_event` | 18 | crunchbase |
| `technology_install` | 8 | builtwith |
| `content_download` | 10 | marketing_automation |
| `case_study_view` | 12 | web_analytics |
| `executive_change` | 15 | linkedin |

## Database — Signal Schema Tables

All tables live in the `signal` schema on the shared Supabase instance.

| Table | Purpose |
|---|---|
| `signal.signal_events` | Every signal contribution with weight + reason_text |
| `signal.score_history` | Score snapshots with full JSON breakdown |
| `signal.tribal_patterns` | Patterns from historical closed-won analysis |
| `signal.account_preferences` | Per-rep, per-account snooze/override |
| `signal.alert_log` | Every alert fired, with response tracking |

**Key design:** `score_breakdown` in `score_history` is a JSON array of
signal contributions written at scoring time. This is what makes every
score explainable.

## Relationship to Other Modules

| Module | Relationship |
|---|---|
| **beacon-data** | Source of all synthetic data. Signal copies from `beacon-data/output/`. Never modify beacon-data. |
| **Loop** | Signal reads Loop's CRM and sequence data. Does NOT re-ingest CRM. Open Question: how Signal reads Loop's tables (direct query vs shared view) — not yet decided. |
| **Views** | Signal data feeds 10+ homepage sections across all four roles. `signal_events` and `score_history` are consumed by Views components. |
| **Graph** | Signal would benefit from Graph's hierarchy but does not depend on it in v1. |
| **Intel** | May share Slack bot infrastructure. No data dependency. |

## Build Phases

1. ✅ **Phase 1 — Skeleton:** Adapter interfaces, scoring engine, schema, config
2. 🔲 **Phase 2 — Scoring Engine + Mock Data:** Wire adapters to beacon-data, end-to-end scoring
3. 🔲 **Phase 3 — LLM Layer + MCP Server:** Claude API for explanations, tribal pattern detection, FastMCP server
4. 🔲 **Phase 4 — Alert Delivery:** Alert evaluation, Slack bot, feedback buttons
5. 🔲 **Phase 5 — Dashboard:** Next.js frontend, score breakdown panel, signal timeline
6. 🔲 **Phase 6 — Rep Feedback Loop:** Slack form, feedback aggregation, learning system

**Phase-gating rule:** Do not start Phase N+1 until Phase N is committed and
validated.

## Open Questions (from PRD)

| # | Question | Status |
|---|---|---|
| 1 | How does Signal read Loop's CRM data? Direct query vs shared view. | **Not decided** — stubbed to mock data |
| 5 | New Slack bot or extend Intel's existing bot? | **Not decided** — needed before Phase 4 |

## Key Reference Repos

| Repo | Path | Use |
|---|---|---|
| beacon-data | `C:\Dev\beacon-data` | Source of truth for synthetic data. Read only. |
| beacon-loop | `C:\Dev\beacon-loop` | Schema reference for CRM tables. Read only. |

## Key Notion Pages

| Page | URL |
|---|---|
| Signal Hub | https://www.notion.so/Signal-Rep-Signal-Prioritization-Engine-3330592291a881f3a242c455de2f91a0 |
| Master PRD | https://www.notion.so/Beacon-Platform-Master-PRD-3330592291a88176ba60d01a7a7bc7fb |
| Views PRD | https://www.notion.so/33a0592291a881e0979ada03782608be |

## Environment Variables

Required in `.env` (never read or output this file):

- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SERVICE_KEY` — Service role key (not anon key)
- `ANTHROPIC_API_KEY` — Claude API key
- `SLACK_BOT_TOKEN` — Slack bot token (Phase 4)
- `SLACK_APP_TOKEN` — Slack app-level token (Phase 4)
- `DEMO_MODE` — Set to `true` for synthetic data mode (default)

## Common Commands

```bash
# Activate virtual environment
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy synthetic data from beacon-data
cp ../beacon-data/output/*.json data/synthetic/
cp ../beacon-data/output/*.csv data/synthetic/

# Run scoring engine (Phase 2+)
python pipeline/run_scoring.py
```

## Response Format

- Show only the file(s) being changed and the specific diff or replacement
- One concept at a time — do not bundle unrelated changes
- If a change touches more than 3 files, flag it and confirm before proceeding

## Keeping This File Up to Date

Update CLAUDE.md when:
- The repo structure changes (new module, new output file)
- A new hard rule is identified — something CC got wrong that wasn't covered
- Build phases complete
- Database tables change
- MCP tools change
- Common commands change

The rule: **if a future CC session would get it wrong without knowing what you
just built, update this file now.**
