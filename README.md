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
      mock_signals.json  # Synthetic data (Phase 2)

    migrations/
      001_signal_schema.sql  # Supabase schema

## Setup

    python -m venv venv
    venv\Scripts\activate
    pip install -r requirements.txt
    cp .env.example .env
    # Edit .env with your keys

## Demo Mode

DEMO_MODE=true (default) loads synthetic data from data/. All adapters read from mock files. Schema is identical to production.

## Stack

- Python — ingestion, scoring, MCP server
- Supabase (PostgreSQL) — signal schema
- Claude API — score explanations, tribal patterns
- FastMCP — Claude Desktop integration
- Slack SDK — alert delivery
- Next.js — dashboard (Phase 5)

## Build Phases

1. ✅ Skeleton — adapter interfaces, scoring engine, schema, config
2. 🔲 Scoring engine + mock data
3. 🔲 LLM layer + MCP server
4. 🔲 Alert delivery (Slack)
5. 🔲 Dashboard (Next.js)
6. 🔲 Rep feedback loop polish
