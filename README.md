# Beacon Signal

**Rep Signal Prioritization Engine** — the middleware that answers "who do I call first?"

Signal ingests multi-source account signals (job changes, intent data, engagement, funding, CRM activity), applies a configurable weighted scoring model with time decay and velocity tracking, and outputs a prioritized account list with plain-English reasoning for every score.

## What makes Signal different

- **Every score is explainable.** Reps see exactly which signals fired and what weight each carried. No black boxes.
- **Tribal pattern detection.** Patterns from historical closed-won deals are surfaced automatically and validated by rep feedback.
- **Rep feedback loop.** Reps confirm or reject scores. The system learns.
- **Configurable at two levels.** Managers set org-level bounds. Reps tune within those bounds.
- **Alert delivery where reps work.** Morning digest + real-time alerts in Slack.

## Architecture

    pipeline/
      adapters/       # One adapter per signal source (5 types)
      scorer.py       # Weighted scoring engine with time decay + velocity
      decay.py        # Time decay utilities
      config.py       # Config loader

    alerts/
      engine.py       # Alert evaluation (Phase 4)

    server/
      server.py       # FastMCP server for Claude Desktop (Phase 3)

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

## Demo Mode

DEMO_MODE=true (default) reads from data/synthetic/. All adapters go through
DataLoader. Schema is identical to production — swapping in live adapters
requires no changes to the scoring engine.

## Stack

- Python — ingestion, scoring, MCP server
- Supabase (PostgreSQL) — signal schema
- Claude API — score explanations, tribal patterns
- FastMCP — Claude Desktop integration
- Slack SDK — alert delivery
- Next.js — dashboard (Phase 5)

## Build Phases

1. ✅ Skeleton — adapter interfaces, scoring engine, schema, config
2. ✅ Scoring engine + mock data — adapters wired to beacon-data synthetic signals, end-to-end scoring working
3. 🔲 LLM layer + MCP server
4. 🔲 Alert delivery (Slack)
5. 🔲 Dashboard (Next.js)
6. 🔲 Rep feedback loop polish
