"""AI-powered deep analysis — LLM trade pattern recognition.

This module sends the bot's performance data to Google Gemini (free tier)
for deeper pattern recognition. While the rule-based checks in engine.py
catch obvious issues (win rate below 40%), the LLM can spot subtler
patterns like:

    - "Your bot does well with momentum in trending markets, but the
       ATR multiplier is too tight — you're getting stopped out before
       the move completes."
    - "You consistently lose on Monday mornings. This might be due to
       weekend gap volatility. Consider sitting out the first 30 minutes."

HOW IT WORKS:
    1. We gather all analysis data (strategies, heatmap, patterns, etc.)
    2. We format it into a structured prompt for the LLM
    3. The LLM analyzes the data and returns:
       - Observations (journal entries — things it noticed)
       - Proposals (concrete parameter changes with reasoning)
    4. We parse the response and save to the database

WHY GEMINI?
    Google Gemini offers a generous free tier (15 requests/minute with
    Gemini 2.0 Flash). No credit card needed — just get an API key at
    https://aistudio.google.com/apikey and add it to your .env file
    as GEMINI_API_KEY.

WHEN TO USE:
    - On-demand: User clicks "Run Deep Analysis" in the Analysis tab
    - Weekly: Could be scheduled via a cron job or the bot's main loop
    - After backtests: To analyze what went wrong or right

Usage:
    from analysis.claude_analyzer import run_deep_analysis

    result = run_deep_analysis(source="live")
    # result = {"observations": [...], "proposals": [...]}
"""

import json
import os
from typing import Any

from analysis.engine import (
    get_day_of_week_patterns,
    get_heatmap,
    get_overview,
    get_strategy_breakdown,
    get_streak_analysis,
    get_symbol_breakdown,
    run_daily_checks,
)
from config.settings import (
    DAILY_LOSS_LIMIT,
    DAILY_PROFIT_TARGET,
    MAX_OPEN_POSITIONS,
    RISK_PER_TRADE_PCT,
    STOP_LOSS_ATR_MULTIPLIERS,
)
from database.db import insert_proposal


def _get_gemini_model() -> Any:
    """Create a Google Gemini model client using the API key from environment.

    The API key should be set in your .env file as GEMINI_API_KEY.
    Get a free key at https://aistudio.google.com/apikey

    If the key isn't set, this function returns None (and deep analysis
    will be unavailable).

    Returns:
        A google.generativeai.GenerativeModel instance, or None if
        the key isn't set or the package isn't installed.
    """
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        return genai.GenerativeModel("gemini-2.0-flash")
    except ImportError:
        # google-generativeai package not installed yet.
        return None


def _gather_analysis_data(source: str = "live") -> dict[str, Any]:
    """Collect all analysis data into one dict for the LLM to review.

    This gathers everything the rule-based engine produces and packages
    it into a structured format that the LLM can analyze.

    Args:
        source: "live" or "backtest".

    Returns:
        A dict with all analysis sections (overview, strategies,
        heatmap, patterns, streaks, existing observations).
    """
    return {
        "source": source,
        "overview": get_overview(source),
        "strategies": get_strategy_breakdown(source),
        "heatmap": get_heatmap(source),
        "day_of_week": get_day_of_week_patterns(source),
        "symbols": get_symbol_breakdown(source),
        "streaks": get_streak_analysis(source),
        "rule_based_observations": run_daily_checks(source),
        "current_settings": {
            "risk_per_trade_pct": RISK_PER_TRADE_PCT,
            "max_open_positions": MAX_OPEN_POSITIONS,
            "daily_profit_target": DAILY_PROFIT_TARGET,
            "daily_loss_limit": DAILY_LOSS_LIMIT,
            "stop_loss_atr_multipliers": STOP_LOSS_ATR_MULTIPLIERS,
        },
    }


def _build_prompt(data: dict[str, Any]) -> str:
    """Build the analysis prompt for the LLM.

    We give the LLM a structured view of all the bot's performance data
    and ask it to act as a trading performance analyst. The prompt
    includes the current bot settings so the LLM can suggest specific
    parameter changes.

    Args:
        data: The gathered analysis data from _gather_analysis_data().

    Returns:
        A formatted prompt string.
    """
    return f"""You are a trading bot performance analyst. Analyze this trading data and provide insights.

## Current Bot Settings
- Risk per trade: {data['current_settings']['risk_per_trade_pct'] * 100}% of portfolio
- Max open positions: {data['current_settings']['max_open_positions']}
- Daily profit target: ${data['current_settings']['daily_profit_target']}
- Daily loss limit: ${data['current_settings']['daily_loss_limit']}
- Stop-loss ATR multipliers: {json.dumps(data['current_settings']['stop_loss_atr_multipliers'])}

## Performance Overview ({data['source']} data)
- Total P&L: ${data['overview']['total_pnl']:,.2f}
- Total trades: {data['overview']['total_trades']}
- Win rate: {data['overview']['win_rate']}%
- Average daily P&L: ${data['overview']['avg_daily_pnl']:,.2f}
- Current streak: {data['overview']['current_streak']} days
- Improving: {data['overview']['improving']}

## Strategy Breakdown
{json.dumps(data['strategies'], indent=2)}

## Strategy x Market Condition Heatmap
Strategies: {data['heatmap']['strategies']}
Conditions: {data['heatmap']['conditions']}
Cells: {json.dumps(data['heatmap']['cells'], indent=2)}

## Day of Week Performance
{json.dumps(data['day_of_week'], indent=2)}

## Top Symbols
{json.dumps(data['symbols'][:15], indent=2)}

## Streak Analysis
- Max winning streak: {data['streaks']['max_winning_streak']} days
- Max losing streak: {data['streaks']['max_losing_streak']} days
- After a win, next day win rate: {data['streaks']['after_win_win_rate']}%
- After a loss, next day win rate: {data['streaks']['after_loss_win_rate']}%

## Existing Rule-Based Observations
{json.dumps(data['rule_based_observations'], indent=2)}

---

Respond with valid JSON in this exact format:
{{
  "observations": [
    {{
      "severity": "info|warning|alert",
      "title": "Short title",
      "message": "Detailed explanation of what you noticed"
    }}
  ],
  "proposals": [
    {{
      "title": "Short action title",
      "description": "Why this change should be made and what improvement to expect",
      "parameter_changes": {{"setting_name": new_value}},
      "current_values": {{"setting_name": current_value}},
      "replay_date": "YYYY-MM-DD or null"
    }}
  ]
}}

Guidelines:
- Only suggest proposals for concrete, measurable parameter changes
- Valid parameter names: risk_per_trade_pct, max_open_positions, daily_profit_target, daily_loss_limit, stop_loss_atr_multipliers.momentum, stop_loss_atr_multipliers.mean_reversion, stop_loss_atr_multipliers.breakout, stop_loss_atr_multipliers.etf_rotation
- Include 2-5 observations (patterns, trends, correlations)
- Include 0-3 proposals (only if the data supports a clear improvement)
- If there isn't enough data, say so in an observation and don't force proposals
- Be specific — reference actual numbers from the data
- For replay_date, suggest specific dates where a different approach might have worked better (or null if not applicable)
"""


def run_deep_analysis(source: str = "live") -> dict[str, Any]:
    """Run LLM-powered deep analysis on trading data.

    This is the main entry point. It gathers data, sends it to Google
    Gemini, parses the response, and saves any proposals to the database.

    Args:
        source: "live" or "backtest".

    Returns:
        A dict with:
            observations: list of observation dicts
            proposals: list of proposal dicts (with their database IDs)
            error: error message if something went wrong (or None)
    """
    # Step 1: Gather all analysis data.
    data = _gather_analysis_data(source)

    # Check if there's enough data to analyze.
    if data["overview"]["total_trades"] < 5:
        return {
            "observations": [{
                "severity": "info",
                "title": "Not enough data",
                "message": (
                    f"Only {data['overview']['total_trades']} trades found. "
                    "The AI needs at least 5 trades to provide meaningful analysis. "
                    "Run some more trades or a backtest first."
                ),
            }],
            "proposals": [],
            "error": None,
        }

    # Step 2: Check for Gemini API key.
    model = _get_gemini_model()
    if model is None:
        return {
            "observations": [{
                "severity": "warning",
                "title": "Gemini API not configured",
                "message": (
                    "Add GEMINI_API_KEY to your .env file to enable "
                    "AI-powered deep analysis. Get a free API key at "
                    "https://aistudio.google.com/apikey"
                ),
            }],
            "proposals": [],
            "error": "GEMINI_API_KEY not set",
        }

    # Step 3: Build prompt and call Gemini.
    prompt = _build_prompt(data)

    try:
        response = model.generate_content(prompt)

        # Step 4: Parse the response.
        response_text = response.text

        # The LLM should return JSON, but sometimes wraps it in markdown.
        # Strip any markdown code fence if present.
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0]

        result = json.loads(response_text.strip())

        observations = result.get("observations", [])
        proposals = result.get("proposals", [])

        # Step 5: Save proposals to the database.
        saved_proposals = []
        for p in proposals:
            proposal_id = insert_proposal(
                title=p["title"],
                description=p["description"],
                source="gemini",
                parameter_changes=p.get("parameter_changes"),
                current_values=p.get("current_values"),
                replay_date=p.get("replay_date"),
            )
            saved_proposals.append({**p, "id": proposal_id, "status": "pending"})

        return {
            "observations": observations,
            "proposals": saved_proposals,
            "error": None,
        }

    except json.JSONDecodeError as e:
        return {
            "observations": [{
                "severity": "warning",
                "title": "Analysis parsing error",
                "message": f"Gemini returned a response but it couldn't be parsed: {e}",
            }],
            "proposals": [],
            "error": f"JSON parse error: {e}",
        }
    except Exception as e:
        return {
            "observations": [{
                "severity": "alert",
                "title": "Analysis failed",
                "message": f"Error calling Gemini API: {e}",
            }],
            "proposals": [],
            "error": str(e),
        }
