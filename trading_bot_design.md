# Trading Bot Design — Interview Summary

**Date:** 2026-03-21

---

## Overview

A conservative day trading bot built in Python, targeting consistent small daily gains ($100/day) across US stocks and ETFs. Paper trading via Alpaca before going live.

---

## Platform & Account

- **Broker:** Alpaca (free paper trading API)
- **Starting capital:** $100,000
- **Mode:** Paper trading first

---

## Trading Schedule

- **Market:** US Stocks & ETFs
- **Timeframe:** Day trading (no overnight positions)
- **Active hours:** First hour (9:30–10:30 AM ET) and last hour (3:00–4:00 PM ET)

---

## Strategies

The bot assesses market conditions each morning and selects the best-fit strategy for the day.

### 1. Mean Reversion
- **When:** Range-bound / choppy markets
- **Indicators:** Bollinger Bands + RSI
- **Stop-loss:** 1x ATR (tighter — expects price to revert quickly)

### 2. Momentum / Trend Following
- **When:** Clear directional market move
- **Indicators:** EMA crossovers (9/21 period) + VWAP
- **Stop-loss:** 1.5x ATR (standard)

### 3. Breakout Trading
- **When:** Volatility expanding after a quiet period
- **Indicators:** Volume spike detection + ATR
- **Stop-loss:** 2x ATR (wider — breakouts need room to develop)

### 4. ETF Rotation
- **When:** Always-on baseline allocation layer
- **Indicators:** Relative strength comparison across sector ETFs (e.g., XLK, XLE, XLF)
- **Stop-loss:** 1.5x ATR (standard)

---

## Stock Selection

- **Method:** Dynamic screening each morning
- **Criteria:** Volume, price range, volatility (specifics to be defined during implementation)

---

## Risk Management

| Rule                     | Setting                                      |
|--------------------------|----------------------------------------------|
| Risk per trade           | 0.5–1% of portfolio ($500–$1,000)            |
| Max open positions       | 5–10 simultaneously                          |
| Stop-loss                | ATR-based (dynamic per strategy, see above)  |
| Take-profit              | Fixed target per trade + trailing stop        |
| Daily profit target      | $100 (starting), scales up with consistency   |
| Target scaling           | +$25 after 5 consecutive profitable days      |
| Max daily loss           | $100 (matches daily target)                   |
| Daily loss cool-down     | Bot stops trading for the rest of the day     |

---

## Operations

- **Logging:** Clean console log for every trade (entry, exit, P&L)
- **Manual override:** Panic button — sells all open positions if in market, stays flat if not
- **Notifications:** Console only (no email/push — high trade volume expected)

---

## Technical Stack

- **Language:** Python
- **Broker API:** Alpaca (alpaca-trade-api SDK)
- **Data:** Alpaca market data (real-time for paper trading)
- **Indicators:** To be determined (likely `ta` or `pandas-ta` library)

---

## Next Steps

1. Create Alpaca paper trading account and get API keys
2. Set up project structure
3. Build market condition assessor (strategy selector)
4. Implement strategies one by one
5. Build risk management layer
6. Add dynamic stock screener
7. Add console logging and manual override
8. Backtest strategies with historical data
9. Run in paper trading mode
