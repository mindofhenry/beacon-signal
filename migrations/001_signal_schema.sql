-- Beacon Signal — Schema Migration
-- Creates `signal` schema and all core tables.
-- Signal tables go in `signal` schema, NOT `public` (Loop owns `public`).
--
-- NOTE: All ID columns use TEXT (not UUID) to match beacon-data's string IDs
-- (sf_acc_011, sdr_1, sig_00001, etc.). Migration applied 2026-04-12.

CREATE SCHEMA IF NOT EXISTS signal;

-- signal_events
CREATE TABLE signal.signal_events (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_value JSONB NOT NULL DEFAULT '{}',
    weight_applied NUMERIC NOT NULL DEFAULT 0,
    reason_text TEXT NOT NULL DEFAULT '',
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    contributed_to_score_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- score_history
CREATE TABLE signal.score_history (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    rep_id TEXT,
    final_score NUMERIC NOT NULL DEFAULT 0,
    score_breakdown JSONB NOT NULL DEFAULT '[]',
    tribal_pattern_id TEXT,
    tribal_pattern_text TEXT,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    rep_feedback TEXT
);

ALTER TABLE signal.signal_events
    ADD CONSTRAINT fk_signal_events_score
    FOREIGN KEY (contributed_to_score_id)
    REFERENCES signal.score_history(id)
    ON DELETE SET NULL;

-- tribal_patterns
CREATE TABLE signal.tribal_patterns (
    id TEXT PRIMARY KEY,
    pattern_name TEXT NOT NULL,
    pattern_description TEXT NOT NULL DEFAULT '',
    signal_conditions JSONB NOT NULL DEFAULT '{}',
    historical_conversion_rate NUMERIC NOT NULL DEFAULT 0,
    sample_size INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_validated_at TIMESTAMPTZ
);

ALTER TABLE signal.score_history
    ADD CONSTRAINT fk_score_history_tribal
    FOREIGN KEY (tribal_pattern_id)
    REFERENCES signal.tribal_patterns(id)
    ON DELETE SET NULL;

-- account_preferences
CREATE TABLE signal.account_preferences (
    rep_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    snoozed_until TIMESTAMPTZ,
    priority_override NUMERIC,
    override_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (rep_id, account_id)
);

-- alert_log
CREATE TABLE signal.alert_log (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    rep_id TEXT NOT NULL,
    alert_tier TEXT NOT NULL CHECK (alert_tier IN ('CRITICAL', 'HIGH', 'STANDARD')),
    alert_type TEXT NOT NULL,
    score_at_fire NUMERIC NOT NULL DEFAULT 0,
    score_breakdown_snapshot JSONB NOT NULL DEFAULT '[]',
    fired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at TIMESTAMPTZ,
    channel TEXT NOT NULL CHECK (channel IN ('slack_dm', 'mcp', 'digest')),
    feedback TEXT
);

-- Indexes
CREATE INDEX idx_signal_events_account ON signal.signal_events(account_id);
CREATE INDEX idx_signal_events_type ON signal.signal_events(signal_type);
CREATE INDEX idx_signal_events_triggered ON signal.signal_events(triggered_at DESC);

CREATE INDEX idx_score_history_account ON signal.score_history(account_id);
CREATE INDEX idx_score_history_rep ON signal.score_history(rep_id);
CREATE INDEX idx_score_history_calculated ON signal.score_history(calculated_at DESC);

CREATE INDEX idx_alert_log_account ON signal.alert_log(account_id);
CREATE INDEX idx_alert_log_rep ON signal.alert_log(rep_id);
CREATE INDEX idx_alert_log_tier ON signal.alert_log(alert_tier);
CREATE INDEX idx_alert_log_fired ON signal.alert_log(fired_at DESC);

CREATE INDEX idx_account_prefs_rep ON signal.account_preferences(rep_id);
