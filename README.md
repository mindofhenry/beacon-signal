# Beacon Signal

**Rep Signal Prioritization Engine** — the middleware that answers "who do I call first?"

Signal ingests multi-source account signals (job changes, intent data, engagement, funding, CRM activity), applies a configurable weighted scoring model with time decay and velocity tracking, and outputs a prioritized account list with plain-English reasoning for every score.

## What makes Signal different

- **Every score is explainable.** Reps see exactly which signals fired and what weight each carried. No black boxes.
- **Tribal pattern detection.** Patterns from historical closed-won deals are surfaced automatically and validated by rep feedback.
- **Rep feedback loop.** Reps confirm or reject scores. The system learns.
- **Configurable at two levels.** Managers set org-level bounds. Reps tune within those bounds.
- **Alert delivery where reps work.** Morning digest + real-time alerts in Slack with full score breakdowns.

## Architecture

    pipeline/
      adapters/       # One adapter per signal source (5 types)
      scorer.py       # Weighted scoring engine with time decay + velocity
      decay.py        # Time decay utilities
      config.py       # Config loader
      explainer.py    # LLM reasoning — Claude API + template fallback

    alerts/
      engine.py       # Alert evaluation — CRITICAL/HIGH/STANDARD tiers
      formatter.py    # Slack Block Kit message formatting
      slack.py        # Slack bot — DM delivery, digest, feedback buttons

    server/
      server.py       # FastMCP server for Claude Desktop (5 tools)

    config/
      weights.yaml    # Signal weights, decay, velocity settings
      alert_thresholds.yaml  # Alert tier definitions

    data/
      synthetic/         # Copied from beacon-data/output/ — never generated here
        signal_events.json      (~5987 signal events)
        score_history.json      (~3017 weekly score snapshots)
        tribal_patterns.json    (7 patterns)
        account_preferences.json (25 snooze/override records)
        alert_log.json          (~1394 alerts)
        sf_accounts.csv         (500 accounts)
        sf_contacts.csv         (~247 contacts)
        sf_opportunities.csv    (~208 opportunities)
        reps.json               (19 reps)

    pipeline/
      data_loader.py     # Loads all synthetic data, provides typed accessors
      run_scoring.py     # End-to-end scoring demo — runs in demo mode

    scripts/
      test_mcp_tools.py  # MCP server validation
      test_alerts.py     # Alert engine validation

    migrations/
      001_signal_schema.sql  # Supabase schema

## Setup

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env
    # Edit .env with your keys

    # Copy synthetic data from beacon-data (if regenerating)
    cp ../beacon-data/output/*.json data/synthetic/
    cp ../beacon-data/output/*.csv data/synthetic/

## Running the scoring engine (Phase 2)

    python pipeline/run_scoring.py

Outputs the top 10 accounts by score with signal breakdowns, decay factors,
velocity bonuses, and tribal pattern matches. Runs entirely on synthetic data
with no external dependencies.

## Running the alert system (Phase 4)

    # Validate alert engine
    python scripts/test_alerts.py

    # Run Slack bot (console mode if no Slack tokens)
    python alerts/slack.py

The alert system evaluates scored accounts against configurable thresholds:

- **CRITICAL** — Score > 80 or re-engagement window detected (dark 30+ days then active). Delivered as real-time Slack DM.
- **HIGH** — Score > 60 with no signals in 48 hours. Delivered as real-time Slack DM.
- **STANDARD** — Morning digest with top 5 accounts per rep.

Every alert includes the full score breakdown. Max 3 real-time alerts per rep per day. Snoozed accounts are excluded.

Without Slack credentials, the bot prints formatted alerts to console for validation.

## Demo Mode

DEMO_MODE=true (default) reads from data/synthetic/. All adapters go through
DataLoader. Schema is identical to production — swapping in live adapters
requires no changes to the scoring engine.

## Stack

- Python — ingestion, scoring, MCP server, alert delivery
- Supabase (PostgreSQL) — signal schema
- Claude API — score explanations, tribal patterns
- FastMCP — Claude Desktop integration
- Slack SDK + Bolt — alert delivery, feedback buttons
- Next.js — dashboard (Phase 5)

## Build Phases

1. ✅ Skeleton — adapter interfaces, scoring engine, schema, config
2. ✅ Scoring engine + mock data — adapters wired to beacon-data synthetic signals, end-to-end scoring working
3. ✅ LLM layer + MCP server — Claude API explainer with template fallback, FastMCP with 5 tools
4. ✅ Alert delivery — evaluation engine, Slack bot with feedback buttons, morning digest, console fallback
5. 🔲 Dashboard (Next.js)
6. 🔲 Rep feedback loop polish
