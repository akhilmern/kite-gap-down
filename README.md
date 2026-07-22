# Gap-Down Fill Trading System — Kite Connect

Automated NSE equity gap-down fill trading system using the **Kite Connect** broker API.

| Component | Port |
|-----------|------|
| Backend (FastAPI) | **6666** |
| Frontend (Vite/React) | **5555** |

---

## Quick Start

### 1. Backend

```bash
# Create and activate virtualenv (Python 3.12+)
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env
cp .env.example .env

# Start
python backend/run.py
```

### 2. Frontend (dev)

```bash
cd frontend
npm install
npm run dev          # http://localhost:5555
```

### 3. Production (build frontend + serve via FastAPI)

```bash
chmod +x deploy.sh && ./deploy.sh
```

---

## Kite Connect Setup

1. Create an app at [https://developers.kite.trade](https://developers.kite.trade)
2. Set redirect URL to `http://localhost:6666/api/auth/callback` (or your server IP)
3. Add your `KITE_API_KEY` and `KITE_API_SECRET` to `.env`
4. For order postbacks, set your Kite app's postback URL to `http://<server>:6666/api/kite/postback`

---

## Daily Workflow

| Time | Event |
|------|-------|
| **08:00 IST** | Auto state reset |
| **08:30 IST** | Auto prev-close fetch |
| **09:08 IST** | Auto gap scan |
| **09:14:55 IST** | SL engine auto-arms |
| **09:15:01 IST** | Queued orders fire |

1. Open `http://localhost:5555`
2. Click **Login with Kite** → Authenticate
3. Click **Start Stream** → WebSocket/postback + poller active
4. (Optional) Click **Fetch Vol History** → pre-cache 20-day volumes
5. At **09:08** — auto scan runs; candidates appear in table
6. Click **Fetch Depth** → pre-open order book imbalances loaded
7. Sort by **Buy %** — higher = more bullish pre-open
8. Select candidates, adjust amounts/prices/SL/Target per row
9. Click **Place Buy Orders** → queued if before 09:15:01; fires automatically
10. Exits managed automatically (synthetic OCO)

---

## Architecture

```
backend/
├── api/routes.py          # 43 REST endpoints
├── config/settings.py     # Pydantic settings + runtime settings
├── execution/
│   ├── buy_executor.py    # Order placement (immediate + queued)
│   ├── exit_engine.py     # Synthetic OCO (SL + target)
│   └── backup_poller.py   # REST fallback poller
├── models/
│   ├── schemas.py         # All Pydantic models
│   └── state.py           # In-memory StateManager singleton
├── scanner/gap_scanner.py # Gap detection + depth analysis
├── scheduler/jobs.py      # APScheduler cron + fire watcher
├── utils/kite_client.py   # Kite Connect REST client
└── websocket/
    ├── order_stream.py    # Order postback handler
    └── market_feed.py     # LTP polling for market-sell SL

frontend/src/
├── App.tsx                # Main shell, all queries/mutations
├── components/
│   ├── CandidatesTable.tsx
│   ├── PositionsTable.tsx
│   └── SettingsPanel.tsx
├── services/api.ts        # Axios typed API client
├── types/index.ts         # TypeScript interfaces
└── index.css              # Design system (light + dark)
```

---

## API Reference

Base URL: `http://localhost:6666/api`  
Swagger UI: `http://localhost:6666/docs`

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/auth/login-url` | Get Kite OAuth login URL |
| POST | `/auth/callback?code=…` | Exchange request token |
| POST | `/auth/direct-token` | Inject token directly |
| POST | `/scanner/run` | Run gap-down scan |
| POST | `/scanner/preopen-depth` | Fetch pre-open order book |
| POST | `/orders/place-buy` | Place (or queue) buy orders |
| GET | `/positions` | All tracked positions |
| GET | `/engine/status` | Engine + WS status |
| POST | `/engine/arm` | Arm exit engine |
| GET | `/health/preflight` | Dashboard preflight data |
| POST | `/kite/postback` | Kite order postback receiver |

---

## Feature Flags

| Flag | Default | Description |
|------|---------|-------------|
| `SCHEDULED_FIRE_ENABLED` | true | Queue orders, fire together at 09:15:01 |
| `ADOPT_MOBILE_BUY_ORDERS` | true | Auto-detect broker-app orders |
| `SL_ENGINE_ENABLED` | true | Exit engine active |
| `SL_ENABLED` | true | Place SL-M orders |
| `MARKET_SELL_SL_ENABLED` | false | LTP polling SL mode |
| `DISABLE_BACKUP_POLLER` | false | Disable REST polling fallback |
| `WRITE_ENV_FROM_UI` | true | Persist UI settings to .env |

---

*Built with FastAPI + React + Kite Connect*
