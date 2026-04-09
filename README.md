# Multi-Agent Paper Trading Platform 🤖📈

An asynchronous, message-bus driven algorithmic trading platform built using the **Fyers API v3**. The system uses a multi-agent architecture to completely separate research (alpha generation), risk management (capital preservation), and execution (portfolio simulation).

It supports both **Live Paper Trading** (polling live market ticks) and **Historical Backtesting** (replaying exactly how the agents would have reacted to past data).

---

## 🏗️ Architecture

The system is decoupled using `asyncio.Queue` message buses, allowing agents to run concurrently without blocking each other.

1. **Data Layer (`FyersDataFetcher`)**: 
   Fetches raw live ticks or historical candles from Fyers API. Publishes `market.tick` events.
2. **Research Agent (`ResearchAgent`)**:
   Consumes `market.tick` events, builds internal OHLCV histories, runs technical indicator formulas (RSI, MACD, Bollinger Bands, ATR), and evaluates them using an ML/Rule-based model to emit `trade.signal` events (`BUY`, `SELL`, `HOLD`).
3. **Risk Agent (`RiskAgent`)**:
   Intercepts every `trade.signal`. It checks the live paper portfolio against rules: `MAX_POSITION_PCT`, `MAX_EXPOSURE_PCT`, and `MAX_DAILY_LOSS_PCT`. Approves the signal (`trade.approved`) or rejects it (`trade.rejected`).
4. **Execution Agent (`ExecutionAgent`)**:
   Listens for `trade.approved`. It simulates slippage latency, executes trades against the `PaperPortfolio`, tracks unrealized/realized P&L, and manages available cash.

---

## ⚙️ Setup & Installation

**1. Create a Python Virtual Environment**
```bash
python -m venv trading-env
source trading-env/bin/activate
```

**2. Install Dependencies**
```bash
pip install -r requirements.txt
```

**3. Configure your Fyers App**
1. Go to the [Fyers API Dashboard](https://myapi.fyers.in/) and create a new App.
2. Ensure you check **ALL** permissions (Data API, Historical Data, Quotes, Orders, Positions, Profile).
3. Set your **Primary IP Address** to `127.0.0.1` (or your public IP).
4. Set your **Redirect URL** exactly to `http://127.0.0.1`.
5. Note down your `App ID` (Client ID) and `App Secret`.

**4. Environment Variables**
Create a `.env` file in the root directory (or use the existing one). Fill in your Client ID and Secret Key:
```env
FYERS_CLIENT_ID=YOUR_APP_ID-100
FYERS_SECRET_KEY=YOUR_APP_SECRET
PAPER_PORTFOLIO_CAPITAL=1000000
TRADING_SYMBOLS=NSE:RELIANCE-EQ,NSE:HDFCBANK-EQ
```

---

## 🔑 Authentication (Daily Access Token)

Fyers Access Tokens expire daily. You must generate a new token at the start of every trading day.

Run the built-in authenticator script:
```bash
python test.py
```
1. Click the login URL generated in the terminal.
2. Log in to Fyers. You will be redirected to an empty `localhost` page.
3. Look at your browser's address bar and copy the huge string labeled `auth_code=...`
4. Paste it back into your terminal.

The script will automatically grab the `access_token` and rewrite your `.env` file!

---

## 🚀 Usage

### 🔙 Backtesting Mode
Run a historical simulation on your chosen symbols right from the terminal. The backtester will replay X days of history, simulate the agent decisions, and print a full performance report.

```bash
# Run default 30-day backtest
python main.py --backtest

# Run custom date range
python main.py --backtest --from-date 2026-03-01 --to-date 2026-04-01
```

### 🔴 Live Paper Trading Mode
Start the live system. Agents will poll data every 5 seconds (configurable) during market hours and simulate paper trades in real-time.

```bash
python main.py --live
```

---

## 🎛️ Risk Parameters Configuration
You can tune the Risk Agent's tight rules inside `.env`:

- `MAX_POSITION_PCT=0.20` (No single asset can exceed 20% of your portfolio)
- `MAX_EXPOSURE_PCT=0.80` (Keep at least 20% in raw cash always)
- `MAX_DAILY_LOSS_PCT=0.03` (Halt trading if the portfolio drops >3% in a day)
- `MAX_VOLATILITY_PCT=0.03` (Reject trades if the asset's ATR% is too high)