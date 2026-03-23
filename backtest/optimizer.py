"""Self-optimizing backtester — finds the best parameter combination.

This module is the bot's "self-improvement engine." Instead of running
one backtest with fixed parameters, it:

    1. GRID SEARCH: Tests many parameter combinations (e.g. stop-loss
       at 1%, 2%, 3% × take-profit at 1%, 1.5%, 2% × risk at 0.5%, 1%).
       Each combination gets a score based on return, win rate, and risk.

    2. AI REFINEMENT: Sends the top results to Google Gemini, which
       analyzes the patterns and suggests refined parameters. Those get
       tested too. Repeats until improvement stops.

The result is the best parameter set found — the bot can then use these
settings for live trading or future backtests.

WHY THIS MATTERS:
    Without optimization, you're guessing at parameters. Should the
    stop-loss be 1.5% or 2.5%? Should you risk 0.5% or 1.5% per trade?
    The optimizer answers these questions with data, not intuition.

Usage:
    # From command line:
    python3 -m backtest.optimizer --start 2025-01-01 --end 2025-03-01

    # From code:
    from backtest.optimizer import run_optimization
    best = run_optimization("2025-01-01", "2025-03-01", market="oslo")
"""

import argparse
import itertools
import time as time_module
from typing import Any


def generate_parameter_grid(
    custom_ranges: dict[str, list] | None = None,
) -> list[dict[str, Any]]:
    """Generate all possible parameter combinations for testing.

    A "grid search" means we test every combination of values. If we
    have 3 values for stop-loss and 3 for take-profit, that's 3×3 = 9
    combinations. Add 3 risk values and it's 3×3×3 = 27.

    The default grid tests sensible ranges for each parameter. You can
    override any parameter range by passing custom_ranges.

    Args:
        custom_ranges: Optional dict mapping parameter names to lists
            of values to test. Any parameter not specified uses the
            default range.

    Returns:
        A list of dicts, each being one parameter combination to test.
        Example: [
            {"stop_loss_pct": 0.015, "take_profit_pct": 0.01, ...},
            {"stop_loss_pct": 0.015, "take_profit_pct": 0.015, ...},
            ...
        ]
    """
    # Default parameter ranges — these are the "knobs" we're tuning.
    # Each list contains the values to try for that parameter.
    defaults: dict[str, list] = {
        # Stop-loss: at what % loss do we exit? (tighter = safer but
        # more false triggers; wider = more room but bigger losses)
        "stop_loss_pct": [0.015, 0.02, 0.03],

        # Take-profit: at what % gain do we exit? (lower = lock in
        # small wins often; higher = bigger wins but less frequent)
        "take_profit_pct": [0.01, 0.02, 0.03],

        # Risk per trade: what % of portfolio to risk on each trade?
        # (lower = smaller positions, less volatile; higher = bigger
        # positions, more potential but more risk)
        "risk_per_trade_pct": [0.005, 0.01, 0.015],

        # Max open positions: how many stocks can we hold at once?
        # (fewer = more focused; more = more diversified)
        "max_open_positions": [5, 10],
    }

    # Apply any custom overrides.
    ranges = {**defaults, **(custom_ranges or {})}

    # Generate all combinations using itertools.product.
    # This is the "grid" in "grid search" — every possible combination.
    keys = list(ranges.keys())
    values = list(ranges.values())

    combinations = []
    for combo in itertools.product(*values):
        param_dict = dict(zip(keys, combo))
        combinations.append(param_dict)

    return combinations


def score_result(report: dict) -> float:
    """Score a backtest result with a single number for ranking.

    We combine multiple metrics into one score so we can sort and
    compare results easily. The scoring weights are:

        - Total return %:   40%  (did we make money?)
        - Win rate:         25%  (are we making good decisions?)
        - Max drawdown:    -20%  (how bad did it get? — penalty)
        - Avg daily P&L:    15%  (consistent daily profit?)

    Higher score = better. A perfect strategy would have high return,
    high win rate, low drawdown, and consistent daily profit.

    Args:
        report: The dict returned by run_backtest(), containing
            total_return_pct, win_rate, max_drawdown_pct, avg_daily_pnl.

    Returns:
        A float score. Higher is better. Can be negative for bad results.
    """
    if not report:
        return -999.0

    # Extract metrics with safe defaults.
    total_return_pct = report.get("total_return_pct", 0)
    win_rate = report.get("win_rate", 0)
    max_drawdown_pct = report.get("max_drawdown_pct", 0)
    avg_daily_pnl = report.get("avg_daily_pnl", 0)

    # Normalise each metric to a roughly 0-100 scale so they contribute
    # proportionally regardless of their natural units.
    #
    # Total return: a 10% return scores 10, 50% scores 50.
    return_score = total_return_pct

    # Win rate: already 0-100.
    wr_score = win_rate

    # Drawdown: penalty. A 5% drawdown penalises by 5.
    drawdown_penalty = max_drawdown_pct

    # Avg daily P&L: normalise by dividing by $10 (so $100/day = 10 points).
    daily_score = avg_daily_pnl / 10.0

    # Weighted combination.
    score = (
        0.40 * return_score
        + 0.25 * wr_score
        - 0.20 * drawdown_penalty
        + 0.15 * daily_score
    )

    return round(score, 3)


def run_grid_search(
    start_date: str,
    end_date: str,
    market: str = "us",
    starting_capital: float = 100_000.0,
    param_grid: list[dict] | None = None,
    quiet: bool = False,
) -> list[dict[str, Any]]:
    """Run backtests for every parameter combination and rank them.

    This is the brute-force search: try everything, score everything,
    sort by score. The top results show which parameter ranges work best.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        market: "us" or "oslo".
        starting_capital: Starting capital in dollars.
        param_grid: List of parameter dicts to test. If None, generates
            a default grid using generate_parameter_grid().
        quiet: If True, suppress individual backtest output.

    Returns:
        A sorted list (best first) of dicts:
            {"params": {...}, "report": {...}, "score": float}
    """
    from backtest.backtester import run_backtest

    if param_grid is None:
        param_grid = generate_parameter_grid()

    total = len(param_grid)
    print(f"\n{'='*60}")
    print(f"  GRID SEARCH: {total} parameter combinations")
    print(f"  Period: {start_date} to {end_date} | Market: {market}")
    print(f"{'='*60}\n")

    results: list[dict[str, Any]] = []
    search_start = time_module.time()

    for i, params in enumerate(param_grid, 1):
        # Show progress.
        print(f"  [{i}/{total}] Testing: "
              f"SL={params.get('stop_loss_pct', '?'):.1%} "
              f"TP={params.get('take_profit_pct', '?'):.1%} "
              f"Risk={params.get('risk_per_trade_pct', '?'):.2%} "
              f"MaxPos={params.get('max_open_positions', '?')}")

        try:
            # Run the backtest with these parameters.
            # We skip DB recording for optimizer runs to keep it fast.
            report = run_backtest(
                start_date=start_date,
                end_date=end_date,
                starting_capital=starting_capital,
                market=market,
                params_override=params,
                name=f"optimizer-{i}",
            )

            result_score = score_result(report)

            results.append({
                "params": params,
                "report": report,
                "score": result_score,
            })

            # Show a brief summary of this run.
            ret = report.get("total_return_pct", 0)
            wr = report.get("win_rate", 0)
            dd = report.get("max_drawdown_pct", 0)
            print(f"         → Return: {ret:+.2f}% | "
                  f"Win rate: {wr:.1f}% | "
                  f"Drawdown: {dd:.1f}% | "
                  f"Score: {result_score:.1f}")

        except Exception as e:
            print(f"         → FAILED: {e}")
            results.append({
                "params": params,
                "report": {},
                "score": -999.0,
            })

    # Sort by score (best first).
    results.sort(key=lambda r: r["score"], reverse=True)

    # Print summary.
    elapsed = time_module.time() - search_start
    print(f"\n{'='*60}")
    print(f"  GRID SEARCH COMPLETE ({elapsed:.0f}s)")
    print(f"{'='*60}")

    if results:
        print(f"\n  TOP 5 RESULTS:\n")
        for rank, r in enumerate(results[:5], 1):
            p = r["params"]
            rep = r["report"]
            print(f"  #{rank} (Score: {r['score']:.1f})")
            print(f"     SL={p.get('stop_loss_pct', '?'):.1%} "
                  f"TP={p.get('take_profit_pct', '?'):.1%} "
                  f"Risk={p.get('risk_per_trade_pct', '?'):.2%} "
                  f"MaxPos={p.get('max_open_positions', '?')}")
            print(f"     Return: {rep.get('total_return_pct', 0):+.2f}% | "
                  f"Win rate: {rep.get('win_rate', 0):.1f}% | "
                  f"Drawdown: {rep.get('max_drawdown_pct', 0):.1f}%")
            print()

    return results


def run_optimization(
    start_date: str,
    end_date: str,
    market: str = "us",
    starting_capital: float = 100_000.0,
    max_rounds: int = 3,
    improvement_threshold: float = 0.5,
) -> dict[str, Any]:
    """Run the full optimization loop: grid search → AI refinement → repeat.

    This is the main entry point for the self-optimizing system.

    Round 1: Grid search tests all parameter combinations.
    Round 2+: Gemini analyzes the top results and suggests refined
              parameters. Those get backtested. If the improvement is
              meaningful (above the threshold), we repeat.

    Args:
        start_date: Backtest start date (YYYY-MM-DD).
        end_date: Backtest end date (YYYY-MM-DD).
        market: "us" or "oslo".
        starting_capital: Starting capital in dollars.
        max_rounds: Maximum number of AI refinement rounds (default 3).
        improvement_threshold: Minimum score improvement to continue
            refining (default 0.5). Below this, we stop — the AI
            can't squeeze out any more gains.

    Returns:
        A dict with:
            - best_params: The best parameter set found.
            - best_score: The score of the best result.
            - best_report: The full backtest report for the best params.
            - all_results: All tested parameter sets and their scores.
            - rounds: How many rounds of refinement were run.
            - ai_suggestions: List of Gemini's suggestions (if any).
    """
    print(f"\n{'#'*60}")
    print(f"  SELF-OPTIMIZATION: {market.upper()} market")
    print(f"  Period: {start_date} to {end_date}")
    print(f"  Max rounds: {max_rounds}")
    print(f"{'#'*60}")

    all_results: list[dict] = []
    ai_suggestions: list[dict] = []

    # --- Round 1: Grid Search ---
    print(f"\n  ROUND 1: Grid Search")
    grid_results = run_grid_search(
        start_date=start_date,
        end_date=end_date,
        market=market,
        starting_capital=starting_capital,
    )
    all_results.extend(grid_results)

    best_score = grid_results[0]["score"] if grid_results else -999
    rounds_completed = 1

    # --- Rounds 2+: AI Refinement ---
    for round_num in range(2, max_rounds + 1):
        print(f"\n  ROUND {round_num}: AI Refinement")

        # Ask Gemini to analyze the top results and suggest new params.
        try:
            from backtest.optimizer_prompts import (
                ask_gemini_for_refinement,
            )

            top_results = all_results[:10]  # Send top 10 to Gemini
            suggestions = ask_gemini_for_refinement(top_results)

            if not suggestions:
                print("  Gemini had no further suggestions. Stopping.")
                break

            ai_suggestions.extend(suggestions)

            # Test each suggestion.
            print(f"  Gemini suggested {len(suggestions)} new combinations.")
            suggestion_results = run_grid_search(
                start_date=start_date,
                end_date=end_date,
                market=market,
                starting_capital=starting_capital,
                param_grid=suggestions,
            )
            all_results.extend(suggestion_results)

            # Re-sort everything by score.
            all_results.sort(key=lambda r: r["score"], reverse=True)

            # Check improvement.
            new_best = all_results[0]["score"]
            improvement = new_best - best_score

            print(f"\n  Round {round_num} improvement: {improvement:+.2f} points")

            if improvement < improvement_threshold:
                print(f"  Improvement below threshold ({improvement_threshold}). "
                      f"Stopping.")
                break

            best_score = new_best
            rounds_completed = round_num

        except ImportError:
            print("  AI refinement not available (missing optimizer_prompts).")
            break
        except Exception as e:
            print(f"  AI refinement failed: {e}")
            break

    # --- Final Results ---
    all_results.sort(key=lambda r: r["score"], reverse=True)
    best = all_results[0] if all_results else {}

    print(f"\n{'#'*60}")
    print(f"  OPTIMIZATION COMPLETE")
    print(f"  Rounds: {rounds_completed} | "
          f"Combinations tested: {len(all_results)}")
    if best:
        print(f"\n  BEST PARAMETERS:")
        for k, v in best.get("params", {}).items():
            if isinstance(v, float) and v < 1:
                print(f"    {k}: {v:.3%}")
            else:
                print(f"    {k}: {v}")
        rep = best.get("report", {})
        print(f"\n  PERFORMANCE:")
        print(f"    Return:   {rep.get('total_return_pct', 0):+.2f}%")
        print(f"    Win rate: {rep.get('win_rate', 0):.1f}%")
        print(f"    Drawdown: {rep.get('max_drawdown_pct', 0):.1f}%")
        print(f"    Score:    {best.get('score', 0):.1f}")
    print(f"{'#'*60}\n")

    return {
        "best_params": best.get("params", {}),
        "best_score": best.get("score", -999),
        "best_report": best.get("report", {}),
        "all_results": [
            {"params": r["params"], "score": r["score"]}
            for r in all_results
        ],
        "rounds": rounds_completed,
        "ai_suggestions": ai_suggestions,
    }


# ------------------------------------------------------------------
# Command-line interface
# ------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Optimize trading bot parameters via grid search + AI."
    )
    parser.add_argument(
        "--start", required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end", required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--market", choices=["us", "oslo"], default="us",
        help="Market: 'us' or 'oslo' (default: us)",
    )
    parser.add_argument(
        "--capital", type=float, default=100_000.0,
        help="Starting capital (default: 100000)",
    )
    parser.add_argument(
        "--rounds", type=int, default=3,
        help="Max AI refinement rounds (default: 3)",
    )

    args = parser.parse_args()

    run_optimization(
        start_date=args.start,
        end_date=args.end,
        market=args.market,
        starting_capital=args.capital,
        max_rounds=args.rounds,
    )
