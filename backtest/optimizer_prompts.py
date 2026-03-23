"""AI prompts for the optimizer's refinement loop (powered by Groq).

After the grid search finds the top parameter combinations, we send
those results to Groq (running Llama 3.3 70B) and ask it to suggest
refined parameters. The LLM can spot patterns that a simple grid search
misses — for example, "stop-loss works best between 2-2.5%, so try
2.1% and 2.3%."

This module handles:
    1. Building the prompt (formatting grid search results for the LLM).
    2. Parsing the LLM's response (extracting parameter suggestions).
    3. The main ask_ai_for_refinement() function that ties it together.
"""

import json
import os
from typing import Any


def _build_refinement_prompt(top_results: list[dict]) -> str:
    """Build a prompt asking the LLM to refine trading parameters.

    We show the LLM the top 10 results from the grid search and ask it
    to find patterns and suggest refined values to try next.

    Args:
        top_results: List of the top grid search results, each containing
            "params" (dict of parameter values) and "score" (float).

    Returns:
        A formatted prompt string.
    """
    # Format the results into a readable table for Gemini.
    results_text = ""
    for i, r in enumerate(top_results, 1):
        params = r.get("params", {})
        report = r.get("report", {})
        score = r.get("score", 0)

        results_text += f"""
Rank #{i} (Score: {score:.1f})
  Parameters:
    stop_loss_pct: {params.get('stop_loss_pct', 'N/A')}
    take_profit_pct: {params.get('take_profit_pct', 'N/A')}
    risk_per_trade_pct: {params.get('risk_per_trade_pct', 'N/A')}
    max_open_positions: {params.get('max_open_positions', 'N/A')}
  Results:
    Total return: {report.get('total_return_pct', 0):+.2f}%
    Win rate: {report.get('win_rate', 0):.1f}%
    Max drawdown: {report.get('max_drawdown_pct', 0):.1f}%
    Avg daily P&L: ${report.get('avg_daily_pnl', 0):,.2f}
    Total trades: {report.get('total_trades', 0)}
"""

    return f"""You are a trading strategy optimizer. I ran a grid search testing different parameter combinations for a stock trading bot. Here are the top results, ranked by a composite score (higher = better):

{results_text}

Analyze these results and suggest 3-5 REFINED parameter combinations to test next. Look for:
1. Which parameter ranges produce the best results?
2. Are there sweet spots between the tested values?
3. Do certain parameter combinations work especially well together?

Respond with valid JSON in this exact format:
{{
  "analysis": "Your brief analysis of the patterns you see (2-3 sentences)",
  "suggestions": [
    {{
      "stop_loss_pct": <float>,
      "take_profit_pct": <float>,
      "risk_per_trade_pct": <float>,
      "max_open_positions": <int>,
      "reasoning": "Why you chose these specific values"
    }}
  ]
}}

Rules:
- All values must be within reasonable ranges:
  - stop_loss_pct: 0.005 to 0.05 (0.5% to 5%)
  - take_profit_pct: 0.005 to 0.05 (0.5% to 5%)
  - risk_per_trade_pct: 0.003 to 0.03 (0.3% to 3%)
  - max_open_positions: 3 to 20
- Suggest values BETWEEN the ones already tested (fine-tuning, not random guessing)
- Each suggestion should be different from the others
- Include your reasoning for each suggestion
"""


def _parse_ai_response(response_text: str) -> list[dict[str, Any]]:
    """Parse the LLM's response into a list of parameter dicts.

    The LLM returns JSON with an "analysis" string and a "suggestions"
    list. We extract just the suggestions (parameter dicts).

    Args:
        response_text: The raw text response from Gemini.

    Returns:
        A list of parameter dicts, each suitable for passing to
        run_backtest(params_override=...). Returns an empty list
        if parsing fails.
    """
    try:
        # Strip markdown code fences if present.
        text = response_text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        result = json.loads(text.strip())

        # Log the AI's analysis.
        analysis = result.get("analysis", "")
        if analysis:
            print(f"\n  AI analysis: {analysis}\n")

        suggestions = result.get("suggestions", [])

        # Extract just the parameter fields (drop the "reasoning" key).
        param_dicts = []
        for s in suggestions:
            params = {
                "stop_loss_pct": float(s["stop_loss_pct"]),
                "take_profit_pct": float(s["take_profit_pct"]),
                "risk_per_trade_pct": float(s["risk_per_trade_pct"]),
                "max_open_positions": int(s["max_open_positions"]),
            }

            reasoning = s.get("reasoning", "")
            if reasoning:
                print(f"  Suggestion: SL={params['stop_loss_pct']:.1%} "
                      f"TP={params['take_profit_pct']:.1%} "
                      f"Risk={params['risk_per_trade_pct']:.2%} "
                      f"MaxPos={params['max_open_positions']}")
                print(f"    Reason: {reasoning}")

            param_dicts.append(params)

        return param_dicts

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"  Failed to parse AI response: {e}")
        return []


def ask_gemini_for_refinement(
    top_results: list[dict],
) -> list[dict[str, Any]]:
    """Ask Groq (Llama 3.3 70B) to suggest refined parameters based on grid search results.

    This is the main function called by the optimizer. It:
    1. Builds a prompt from the top grid search results.
    2. Sends it to Groq's API (running Llama 3.3 70B).
    3. Parses the response into parameter dicts.

    The function name is kept as ask_gemini_for_refinement for backwards
    compatibility with the optimizer module that imports it by this name.

    Args:
        top_results: The top N results from the grid search.

    Returns:
        A list of parameter dicts to test. Returns an empty list if
        Groq is not configured or the call fails.
    """
    # Check for Groq API key.
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        print("  GROQ_API_KEY not set — skipping AI refinement.")
        print("  Get a free key at https://console.groq.com")
        return []

    try:
        from groq import Groq
    except ImportError:
        print("  groq package not installed — run: pip install groq")
        return []

    # Build the prompt.
    prompt = _build_refinement_prompt(top_results)

    # Call Groq (Llama 3.3 70B — fast, free, no region restrictions).
    try:
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return _parse_ai_response(response.choices[0].message.content)

    except Exception as e:
        print(f"  Groq API error: {e}")
        return []
