# Trading Bot

A Python-based algorithmic trading bot with a mobile-friendly web dashboard, backtesting engine, and AI-powered analysis. Built to trade US stocks via the Alpaca paper trading API.

## What it does

- **Live trading** — runs automated strategies during market hours based on technical indicators
- **Backtesting** — test strategies against historical data with detailed results
- **Analysis** — tracks which strategies perform best under different market conditions
- **AI insights** — uses Google Gemini to find deeper patterns in your trade history
- **Web dashboard** — monitor the bot from your browser (or phone)

## Tech stack

- **Backend:** Python + Flask
- **Frontend:** React (PWA — installable on your phone)
- **Database:** SQLite
- **Data:** Alpaca API (live prices, news), Yahoo Finance (historical data)
- **AI:** Google Gemini API

## Requirements

- Python 3.10+
- Node.js (for the React frontend)
- An [Alpaca](https://alpaca.markets) account (free paper trading account works)
- A [Google Gemini](https://aistudio.google.com/apikey) API key (free tier works)

## Setup

**1. Clone the repository**
```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
```

**2. Create a virtual environment and install dependencies**
```bash
python -m venv .venv
source .venv/bin/activate   # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**3. Set up your API keys**
```bash
cp .env.example .env
```
Then open `.env` and fill in your real API keys.

**4. Run the bot**
```bash
python main.py
```

The dashboard will be available at `http://localhost:5000`.

## Important

- This bot is configured for **paper trading** (simulated money) by default — no real funds are at risk unless you explicitly switch to a live account
- Never share your `.env` file or commit it to GitHub — it contains your private API keys
- Past backtest performance does not guarantee future results

## Project structure

```
├── main.py              # Entry point
├── strategies/          # Trading strategies
├── broker/              # Alpaca API client
├── backtest/            # Backtesting engine
├── analysis/            # Performance analysis
├── screener/            # Stock screening
├── risk/                # Risk management
├── dashboard/           # Flask web server
├── frontend/            # React app
├── config/              # Bot settings
├── database/            # SQLite helpers
├── utils/               # Shared utilities
├── requirements.txt     # Python dependencies
└── .env.example         # API key template
```
