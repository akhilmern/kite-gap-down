# Gap-Down Fill Trading System

Async NSE gap-down-fill trading system built for Upstox with a FastAPI backend and React/Vite frontend.

## Overview

This project scans NSE equities for gap-down opportunities, lets you select candidates in the UI, places concurrent buy orders, and protects completed buys with an SL-M sell order plus a target limit sell order using application-managed synthetic OCO logic.

Core behavior implemented:
- Async Upstox OAuth login and direct token injection for testing
- NSE equity instrument cache from Upstox JSON instrument dump
- Gap scanner with runtime-configurable filters
- Concurrent buy order placement
- Automatic intraday-to-delivery fallback on product rejection
- SL-first exit placement after buy completion
- Target cancellation on SL fill and SL cancellation on target fill
- Backup order-book poller plus portfolio websocket stream wrapper
- In-memory runtime state only
- Runtime settings API with optional `.env` write-through
- Weekend testing toggle for mock scanner data
- Paper mode toggle

## Project structure

```text
backend/
  api/routes.py
  config/settings.py
  execution/
    backup_poller.py
    buy_executor.py
    exit_engine.py
  models/
    schemas.py
    state.py
  scanner/gap_scanner.py
  scheduler/jobs.py
  tests/test_exit_engine.py
  utils/upstox_client.py
  websocket/order_stream.py
  main.py
  run.py
  requirements.txt
  pytest.ini
frontend/
  src/
    components/
      CandidatesTable.tsx
      PositionsTable.tsx
      SettingsPanel.tsx
    services/api.ts
    types/index.ts
    App.tsx
    main.tsx
    styles.css
  package.json
  vite.config.ts
  tsconfig.json
.env.example
README.md
```

## Requirements

- Python 3.12+
- Node.js 18+
- npm
- Upstox app credentials

## Environment setup

Copy [` .env.example`](.env.example) to [` .env`](.env) and fill in the required values.

Required variables:
- `UPSTOX_CLIENT_ID`
- `UPSTOX_CLIENT_SECRET`
- `UPSTOX_REDIRECT_URI`

Important defaults are already included in [` .env.example`](.env.example), including scanner thresholds, exit settings, backup poller settings, mock mode, and paper mode.

## Backend setup

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
Run the API server:
python3 run.py

```



```bash
./.venv/bin/pip install -r backend/requirements.txt

./.venv/bin/python backend/run.py
```

Backend default URL:
- `http://localhost:7778`
- API prefix: `http://localhost:7778/api`

## Frontend setup

Install dependencies:

```bash
cd frontend
npm install
```

Run the frontend:

```bash
npm run dev
```

Frontend default URL:
- `http://localhost:5173`

The frontend expects `VITE_API_BASE` to point at the backend API. The provided [` .env.example`](.env.example) already includes:

```env
VITE_API_BASE=http://localhost:7778/api
```

## Main API endpoints

Authentication:
- `GET /api/auth/login-url`
- `POST /api/auth/callback?code=...`
- `POST /api/auth/direct-token`
- `GET /api/auth/status`
- `POST /api/auth/start-order-stream`
- `POST /api/auth/stop-order-stream`

Scanner:
- `POST /api/scanner/run`
- `POST /api/scanner/refresh-universe`
- `GET /api/scanner/last-results`

Orders and positions:
- `POST /api/orders/place-buy`
- `GET /api/positions`
- `GET /api/positions/{symbol}`

Engine and settings:
- `GET /api/engine/status`
- `POST /api/engine/arm`
- `POST /api/engine/disarm`
- `GET /api/engine/config`
- `PUT /api/engine/config`
- `GET /api/settings`
- `PUT /api/settings`
- `GET /api/health`
- `GET /api/health/preflight`

## Trading workflow

1. Authenticate with Upstox from the frontend.
2. Start the portfolio order stream.
3. Run the scanner.
4. Select candidates.
5. Enter investment amount per row.
6. Adjust buy price, SL%, target%, or enable market buy per row.
7. Submit buy orders.
8. On buy completion, the backend places:
   - SL-M sell first
   - target limit sell second
9. If either exit fills first, the opposite leg is cancelled.

## Validation

Backend tests:

```bash
./.venv/bin/pytest -c backend/pytest.ini backend/tests/test_exit_engine.py
```

Frontend production build:

```bash
cd frontend
npm run build
```

## Notes and caveats

- Runtime state is in memory only. Restart clears active application state.
- Token persistence is not enabled by default.
- Mock scan mode affects scanner candidates, not broker order placement.
- Paper mode prevents real buy order placement.
- Upstox websocket event payload normalization may need small live-session tuning depending on actual production payload shape.
- Scanner currently uses the full quotes endpoint for richer quote fields.
- Delivery fallback is implemented heuristically from broker rejection text.

## Files to check first

- Backend config: [`backend/config/settings.py`](backend/config/settings.py)
- API routes: [`backend/api/routes.py`](backend/api/routes.py)
- Upstox client: [`backend/utils/upstox_client.py`](backend/utils/upstox_client.py)
- Exit engine: [`backend/execution/exit_engine.py`](backend/execution/exit_engine.py)
- Frontend app shell: [`frontend/src/App.tsx`](frontend/src/App.tsx)
