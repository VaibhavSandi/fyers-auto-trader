# FYERS Auto Trader

A fully automated intraday trading application for the Indian stock market via
**FYERS**, built for someone with **no trading knowledge**. You provide your
capital and a risk comfort level; the application scans the market, decides
what (if anything) to trade, sizes the position, protects it with a
stop-loss/target/trailing-stop, and exits automatically - all using
conservative, rule-based, explainable logic.

> **There is no guaranteed-profit trading strategy, and this application does
> not provide one.** Trading involves real risk of loss. This system is built
> to prioritize capital protection and controlled risk, not to promise
> returns. Start in **Paper Trading** mode and only move to **Live Trading**
> once you understand how it behaves and are comfortable with the risk.

---

## 1. What this application actually does

```
Connect FYERS -> Enter capital -> Pick a risk profile -> Pick Paper/Live -> Press Start
```

From there, every ~20 seconds, the backend's Trading Engine:

1. Checks the broker connection, market status, and system health.
2. Classifies the broad market (NIFTY/BANK NIFTY) as bullish/bearish/neutral/unsafe.
   If it's unsafe or unclear, **it does not trade** that cycle.
3. Scans a curated list of ~50 liquid NSE large-caps and filters out anything
   illiquid, too flat, too wild, or with a bad spread.
4. Scores the remaining candidates (0-10) using multiple independent
   technical confirmations (trend, VWAP, EMAs, volume, momentum, market
   regime, risk/reward). A trade is only taken at 7/10 or higher - no single
   indicator can trigger a trade.
5. Calculates entry, ATR/structure-based stop-loss, and a risk/reward-based
   target for the best-scoring setup.
6. Runs it through the Risk Engine (daily loss limit, consecutive-loss pause,
   max trades/positions, hard ceilings) and sizes the position purely from
   risk-per-share - never by "doubling up" after a loss.
7. Places the order (simulated in Paper mode, real in Live mode), confirms
   the fill, and starts monitoring stop-loss / target / a profit-protecting
   trailing stop.
8. Exits automatically on stop-loss, target, trailing stop, mandatory
   square-off time, or an emergency stop - and records everything in the
   trade journal.

A large **🛑 EMERGENCY STOP / KILL SWITCH** is always visible on the
dashboard and a separate **CLOSE ALL POSITIONS** button exists independently
of it, exactly as required for a safety-critical control.

---

## 2. Project layout

```
fyers-auto-trader/
  backend/            FastAPI app, trading engine, database, tests
    app/
      fyers/           FYERS auth / REST client / websocket feed wrapper
      engine/          scanner, strategy, risk engine, sizing, stops,
                       order manager, position manager, kill switch,
                       reconciliation, recovery, the orchestrator loop
      journal/         trade journal + performance analytics
      api/             FastAPI routes + dashboard WebSocket
      models.py        SQLAlchemy schema (11 tables)
      config.py        all settings, read only from environment/.env
    migrations/        versioned SQL migrations + lightweight runner
    tests/              75 automated tests (pytest)
    requirements.txt, .env.example, run.py
  frontend/            React + TypeScript (Vite) UI
    src/pages/          Setup, Dashboard, Journal
    src/components/     EmergencyStop, CurrentTrade, SystemHealth, TodaySummary
  scripts/             Windows install/start scripts
```

---

## 3. One-time setup (Windows)

### Prerequisites
- **Python 3.11+** (https://www.python.org/downloads/) - check "Add to PATH" during install.
- **Node.js 20 LTS+** (https://nodejs.org/) - includes npm.
- A **FYERS trading account** (only required for Live mode; Paper mode needs
  a FYERS *developer app* for market data, see below).

### 3.1 Create a FYERS API app
1. Log in at https://myapi.fyers.in/dashboard with your FYERS credentials.
2. Create a new app. Set its **Redirect URL** to exactly:
   `http://127.0.0.1:8000/api/auth/fyers/callback`
3. Note down the **App ID (Client ID)** and **Secret Key**.

### 3.2 Install everything
Double-click `scripts\install.bat` (or run `scripts\install.ps1` in
PowerShell). This will:
- create a Python virtual environment and install backend dependencies,
- create `backend\.env` from `backend\.env.example` and generate a unique
  encryption key for you automatically,
- install the frontend's npm dependencies.

### 3.3 Add your FYERS credentials
Open `backend\.env` in Notepad and fill in:
```
FYERS_CLIENT_ID=your-app-id
FYERS_SECRET_KEY=your-secret-key
```
Leave everything else as-is unless you know what you're changing (see
section 8, "Hard safety ceilings").

**Never commit or share your `.env` file - it holds your encryption key and
(once connected) an encrypted copy of your FYERS access token.**

---

## 4. Running the application

Double-click `scripts\start-all.bat`. This opens two windows (backend API on
`http://127.0.0.1:8000`, frontend on `http://127.0.0.1:5173`) and launches
your browser to the app. Close those two windows to stop the app.

You can also start each half separately with `scripts\start-backend.ps1`
and `scripts\start-frontend.ps1` - useful when you want to watch the
backend's log output.

### First run
1. **Setup** page: enter your trading capital, pick a risk profile
   (Conservative/Balanced/Aggressive - each is explained in plain language
   on screen), and choose Paper or Live trading.
2. If you chose Live, click **Connect FYERS Account** - this opens FYERS'
   own login page in a new tab. After you log in there, you're redirected
   back and the app shows "Connected". FYERS access tokens expire daily, so
   you'll reconnect once each trading day.
3. Click **START AUTO TRADING**. The app runs a recovery/health check first;
   if anything looks wrong (no connection, no protection on an existing
   position, etc.) it tells you exactly what, instead of starting anyway.
4. Watch the dashboard. The 🛑 Emergency Stop button is always there if you
   want to stop everything immediately.

---

## 5. Paper vs Live trading

Both modes run through the **exact same** scanner, strategy, and risk
engine. Only the execution layer differs:
- **Paper (🟡):** orders "fill" instantly at the real market price (read
  from FYERS quotes) with a small simulated slippage. No real orders are
  ever sent. Good for understanding how the app behaves before risking money.
- **Live (🔴):** real orders are placed on your FYERS account. Fills are
  confirmed by polling FYERS' order book - the app never assumes a fill
  happened just because the placement call returned.

The mode is always shown clearly in the top-right corner so there is never
ambiguity about which one is active.

---

## 6. Safety systems (what's actually protecting your capital)

| Protection | How |
|---|---|
| Daily capital protection | A max daily loss % (from your risk profile) is converted to a ₹ amount from the day's *starting* capital. Breach -> new trades stop for the day. |
| Consecutive loss protection | After N losing trades in a row (profile-dependent), auto trading pauses for the day. |
| No martingale / no revenge trading | Risk-per-trade is always calculated from the **day's starting capital**, never from live/updated equity - a win never inflates the next trade's size, a loss never shrinks the stop or widens the next bet. |
| Hard ceilings | `backend/.env`'s `HARD_MAX_*` values are an absolute ceiling no profile or setting can ever exceed, even Aggressive. |
| Opening-range skip | No new entries before `ENTRY_START_TIME` (default 09:30 IST) - the first ~15 minutes after the open are typically too volatile/noisy to trust. |
| Mandatory square-off | All open positions are force-closed at `SQUARE_OFF_TIME` (default 15:12 IST); no new entries after `ENTRY_CUTOFF_TIME` (default 14:45 IST). |
| System health gating | If FYERS API, live data, the database, or the order manager report unhealthy, new trades stop automatically. |
| Broker reconciliation | Live mode periodically compares local state to FYERS' own position/order books; broker state always wins. An unexplained broker-side position halts new trades until reviewed. |
| Crash/restart recovery | On every backend start, auto trading is forced OFF and a recovery check (broker reconnect, reconciliation, stop-loss verification) must pass before you can press Start again. |
| Kill switch | Stops new signals/orders, cancels pending orders, and disables auto trading immediately - independent of "Close All Positions", which is a separate, explicit action. |

---

## 7. The strategy, in plain language

No single indicator can trigger a trade. Every candidate stock is scored out
of 10:

```
Trend matches market direction      +2
Price above/below VWAP               +2
Fast average vs slow average         +1
Unusual trading volume               +2
Short-term momentum                  +1
Market condition is clear            +1
Risk/reward is acceptable            +1
----------------------------------------
Minimum to trade: 7 / 10
```

Stop-loss is the wider of an ATR-based distance or recent price structure
(capped so it's never absurd); target is set from the minimum risk/reward
for your profile (capped by a realistic volatility-based ceiling). Every
trade the app takes shows you exactly which of the checks above passed, plus
the ₹ risk and ₹ potential reward, on the dashboard.

See `backend/app/engine/strategy.py` for the exact, commented implementation.

---

## 8. Configuration reference

All configuration lives in `backend/.env` (copy of `.env.example`). Nothing
sensitive is ever hard-coded in source. Key settings:

- `FYERS_CLIENT_ID`, `FYERS_SECRET_KEY`, `FYERS_REDIRECT_URI` - your FYERS app.
- `APP_SECRET_KEY` - encrypts the stored FYERS access token at rest (auto-generated by `install.ps1`).
- `HARD_MAX_DAILY_LOSS_PCT`, `HARD_MAX_RISK_PER_TRADE_PCT`, `HARD_MAX_OPEN_POSITIONS`, `HARD_MAX_TRADES_PER_DAY` - absolute ceilings, independent of risk profile.
- `MARKET_OPEN_TIME`, `MARKET_CLOSE_TIME`, `ENTRY_START_TIME`, `ENTRY_CUTOFF_TIME`, `SQUARE_OFF_TIME` - trading windows (IST).

Per-user settings (capital, risk profile, mode, and the derived numeric
limits) are stored in the database and edited from the Setup page, not the
`.env` file.

---

## 9. Running the tests

```powershell
cd backend
.\venv\Scripts\Activate.ps1
pytest -q
```

75 tests cover: strategy signal scoring, stock filtering/liquidity,
position sizing, stop-loss/target calculation, trailing-stop behaviour,
the daily loss limit, consecutive-loss pausing, duplicate-order
prevention, partial fills, order rejection, FYERS API failure handling,
live-data staleness, broker reconciliation, crash/restart recovery, the
kill switch (dedicated suite), close-all-positions, and end-of-day
square-off. All run against a disposable SQLite database and fully mocked
FYERS responses - no network access or real credentials required.

---

## 10. Troubleshooting

- **"Connect your FYERS account first (live mode)"** - your token has
  expired (they expire daily) or you haven't connected yet today. Go to
  Setup and click Connect FYERS Account again.
- **Recovery check keeps failing** - read the specific failed check shown
  in the error; it names exactly what's wrong (no connection, unresolved
  broker position mismatch, missing stop-loss, etc.).
- **Nothing is trading** - this is often correct behaviour, not a bug: the
  market regime filter is deliberately comfortable saying "no trade today"
  when conditions are unclear or too volatile. Check Journal -> Recent
  Signals to see what was evaluated and why it was rejected.
- **Port already in use** - another instance is probably already running;
  close the existing backend/frontend windows first.

---

## 11. Disclaimer

This software is provided for educational and personal use. It does not
guarantee profit and can lose money, including in Live mode with real
funds. You are solely responsible for your own trading decisions, for
reviewing this code before trusting it with real capital, and for complying
with all applicable regulations. Start with Paper trading and a small
capital amount in Live mode until you have verified the system's behaviour
over multiple sessions.
