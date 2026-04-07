"""
LLM Reasoning Module — generates plain-English explanations for account scores.

Two modes:
1. LLM mode: Calls Claude API (claude-sonnet-4-6) for narrative explanations
2. Template mode: Falls back to structured template when no API key is set

Template fallback is the default for demo sessions and produces genuinely
useful output from score_breakdown data — it's not a placeholder.
"""

import os
from datetime import datetime, timezone

from pipeline.scorer import AccountScore, SignalContribution


# ---------------------------------------------------------------------------
# Template-based explanation (no LLM needed)
# ---------------------------------------------------------------------------

def _format_age(triggered_at: datetime, as_of: datetime) -> str:
    """Human-readable age string."""
    days = (as_of - triggered_at).total_seconds() / 86400
    if days < 1:
        return "today"
    if days < 7:
        return f"{int(days)}d ago"
    if days < 30:
        weeks = int(days / 7)
        return f"{weeks}w ago"
    months = int(days / 30)
    return f"{months}mo ago"


def _signal_type_label(signal_type: str) -> str:
    """Human-readable signal type name."""
    labels = {
        "champion_hired": "Champion hired",
        "economic_buyer_change": "Executive change",
        "champion_departed": "Champion departed",
        "category_research": "Category research surge",
        "competitor_research": "Competitor research detected",
        "pricing_page_visit": "Pricing page visit",
        "demo_request": "Demo requested",
        "content_download": "Content download",
        "case_study_view": "Case study viewed",
        "web_visit": "Website visit",
        "new_funding_round": "New funding round",
        "headcount_growth": "Headcount growth",
        "technology_install": "Technology install",
        "last_activity_recent": "Recent CRM activity",
        "open_opportunity": "Open opportunity",
        "sequence_enrolled": "Sequence enrolled",
    }
    return labels.get(signal_type, signal_type.replace("_", " ").title())


def template_explanation(
    score: AccountScore,
    account_name: str,
    as_of: datetime | None = None,
) -> str:
    """
    Generate a template-based explanation from score_breakdown data.
    Produces useful output without any LLM call.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    # Sort contributions by decayed weight descending
    top = sorted(score.score_breakdown, key=lambda c: abs(c.decayed_weight), reverse=True)

    # Build top signals line (up to 3)
    signal_parts = []
    for c in top[:3]:
        label = _signal_type_label(c.signal_type)
        age = _format_age(c.triggered_at, as_of)
        signal_parts.append(f"{label} {age} (+{c.decayed_weight:.0f})")

    explanation = f"{account_name} scored {score.final_score:.0f} because: {', '.join(signal_parts)}."

    if score.velocity_applied:
        explanation += f" Velocity bonus active (x{score.velocity_multiplier}) — {len(score.score_breakdown)} signals in recent window."

    if score.tribal_pattern_text:
        explanation += f" Matches tribal pattern: {score.tribal_pattern_text}."

    return explanation


# ---------------------------------------------------------------------------
# LLM-based explanation (Claude API)
# ---------------------------------------------------------------------------

def _has_api_key() -> bool:
    """Check if a usable Anthropic API key is configured."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return bool(key) and key != "your_key_here"


def _build_prompt(
    score: AccountScore,
    account_name: str,
    industry: str,
    as_of: datetime,
) -> str:
    """Build the prompt for Claude to generate an explanation."""
    top = sorted(score.score_breakdown, key=lambda c: abs(c.decayed_weight), reverse=True)[:5]

    signal_lines = []
    for c in top:
        age_days = (as_of - c.triggered_at).total_seconds() / 86400
        signal_lines.append(
            f"- {c.signal_type}: raw_weight={c.raw_weight}, "
            f"decay_factor={c.decay_factor:.3f}, "
            f"decayed_weight={c.decayed_weight:.1f}, "
            f"age={age_days:.0f}d, "
            f"reason=\"{c.reason_text}\""
        )

    signals_block = "\n".join(signal_lines)
    velocity_line = (
        f"Velocity bonus: x{score.velocity_multiplier} "
        f"({len(score.score_breakdown)} signals in window)"
        if score.velocity_applied else "No velocity bonus"
    )
    tribal_line = (
        f"Tribal pattern match: {score.tribal_pattern_text}"
        if score.tribal_pattern_text else "No tribal pattern match"
    )

    return f"""You are a sales intelligence assistant. Write a 2-3 sentence explanation of why this account is prioritized.

Account: {account_name}
Industry: {industry}
Final Score: {score.final_score}

Top signal contributions:
{signals_block}

{velocity_line}
{tribal_line}

Write a concise, action-oriented explanation that a sales rep can scan in 5 seconds. Reference the top signals by name, mention velocity if active, and note tribal patterns. No bullet points — just flowing sentences."""


def llm_explanation(
    score: AccountScore,
    account_name: str,
    industry: str,
    as_of: datetime | None = None,
) -> str:
    """
    Call Claude API for a narrative explanation.
    Falls back to template if API key is missing.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    if not _has_api_key():
        return template_explanation(score, account_name, as_of)

    import anthropic

    client = anthropic.Anthropic()
    prompt = _build_prompt(score, account_name, industry, as_of)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def batch_explanations(
    scores: list[AccountScore],
    account_map: dict[str, dict],
    as_of: datetime | None = None,
) -> dict[str, str]:
    """
    Generate explanations for multiple accounts.

    In template mode: generates all locally (fast).
    In LLM mode: batches into a single multi-account prompt to reduce API calls.

    Returns dict of account_id → explanation string.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    if not _has_api_key():
        result = {}
        for score in scores:
            acct = account_map.get(score.account_id, {})
            name = acct.get("Name", score.account_id)
            result[score.account_id] = template_explanation(score, name, as_of)
        return result

    # LLM batch mode — combine into one prompt for efficiency
    import anthropic

    account_blocks = []
    for i, score in enumerate(scores):
        acct = account_map.get(score.account_id, {})
        name = acct.get("Name", score.account_id)
        industry = acct.get("Industry", "Unknown")

        top = sorted(score.score_breakdown, key=lambda c: abs(c.decayed_weight), reverse=True)[:3]
        signal_lines = []
        for c in top:
            age_days = (as_of - c.triggered_at).total_seconds() / 86400
            signal_lines.append(
                f"  - {c.signal_type}: decayed_weight={c.decayed_weight:.1f}, "
                f"age={age_days:.0f}d, reason=\"{c.reason_text}\""
            )
        signals_text = "\n".join(signal_lines)

        velocity = f"velocity x{score.velocity_multiplier}" if score.velocity_applied else "no velocity"
        tribal = f"tribal: {score.tribal_pattern_text}" if score.tribal_pattern_text else "no tribal"

        account_blocks.append(
            f"[{i+1}] {name} (ID: {score.account_id}) | {industry} | "
            f"Score: {score.final_score} | {velocity} | {tribal}\n{signals_text}"
        )

    prompt = f"""You are a sales intelligence assistant. For each account below, write a 2-3 sentence explanation of why it's prioritized. Reference specific signals, mention velocity if active, note tribal patterns.

Format your response as numbered items matching the input. Keep each explanation concise and action-oriented.

{chr(10).join(account_blocks)}"""

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=150 * len(scores),
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse numbered response back into per-account explanations
    response_text = message.content[0].text
    explanations = _parse_batch_response(response_text, scores)
    return explanations


def _parse_batch_response(
    response_text: str,
    scores: list[AccountScore],
) -> dict[str, str]:
    """Parse a numbered batch response into per-account explanations."""
    lines = response_text.strip().split("\n")
    result = {}
    current_idx = None
    current_text = []

    for line in lines:
        # Check if this line starts a new numbered item
        stripped = line.strip()
        for i in range(len(scores)):
            prefix = f"[{i+1}]"
            alt_prefix = f"{i+1}."
            if stripped.startswith(prefix) or stripped.startswith(alt_prefix):
                # Save previous
                if current_idx is not None and current_idx < len(scores):
                    result[scores[current_idx].account_id] = " ".join(current_text).strip()
                current_idx = i
                # Remove the prefix
                text = stripped
                if stripped.startswith(prefix):
                    text = stripped[len(prefix):].strip()
                elif stripped.startswith(alt_prefix):
                    text = stripped[len(alt_prefix):].strip()
                current_text = [text] if text else []
                break
        else:
            if current_idx is not None:
                current_text.append(stripped)

    # Save last item
    if current_idx is not None and current_idx < len(scores):
        result[scores[current_idx].account_id] = " ".join(current_text).strip()

    # Fill any missing with template fallback
    for score in scores:
        if score.account_id not in result:
            result[score.account_id] = template_explanation(
                score, score.account_id, datetime.now(timezone.utc)
            )

    return result
