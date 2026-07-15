# Order Timing Fix Plan

## Top-Level Overview

There are **two distinct bugs** to fix:

1. **Wrong entry timestamp (09:14:12 instead of 09:15:01)** — `entry_time` is set using `datetime.now(IST)` on the backend server *when the COMPLETE WebSocket event arrives*, not from the broker-issued timestamp inside the event. The broker's Upstox order event contains a timestamp in `order_data` (key: `order_creation_time` or equivalent in the raw payload). That broker timestamp should be extracted and used.

2. **No countdown UI for queued orders** — Once a user places orders in the 09:08–09:14:50 queue window, the UI shows them as `PENDING` but gives no indication of how long until they fire at 09:15:00. The backend already computes remaining seconds in `_countdown_loop()` but this data is never sent to the frontend. The `PreflightResponse` should also expose `time_to_market_open_seconds`, and the UI should render it alongside a pending-orders count.

---

## Sub-Task 1 — Extract broker timestamp into `OrderEvent` and use it for `entry_time`

**Status:** [ ] pending

**Intent**
`entry_time` currently records the moment the backend *processes* the COMPLETE event, which is slightly after the actual broker fill. The broker's raw WebSocket event already contains an order-creation/fill timestamp inside `order_data`. We need to extract it into `OrderEvent.order_timestamp` and then use it in `ExitEngine._handle_buy_update()` instead of `datetime.now(IST)`.

**Relevant Context**
- `backend/models/schemas.py` lines 227–241 — `OrderEvent` model; add `order_timestamp: str | None = None`
- `backend/utils/upstox_client.py` lines 467–489 — `normalize_order_event()` builds the `OrderEvent`; extract `order_data.get("order_creation_time") or order_data.get("order_timestamp") or order_data.get("placed_on")` into the new field
- `backend/execution/exit_engine.py` line 70 — `position.entry_time = datetime.now(IST).isoformat()` — replace with `event.order_timestamp or datetime.now(IST).isoformat()`

**Expected Outcomes**
- `OrderEvent` carries an optional `order_timestamp` field.
- `normalize_order_event()` populates it from the raw broker payload.
- `entry_time` on the position reflects the broker-issued timestamp when available; falls back to server time when the field is absent.

**Todo List**
1. In `backend/models/schemas.py`, add `order_timestamp: str | None = None` to `OrderEvent`.
2. In `backend/utils/upstox_client.py` → `normalize_order_event()`, add extraction: `order_timestamp=order_data.get("order_creation_time") or order_data.get("order_timestamp") or order_data.get("placed_on")`.
3. In `backend/execution/exit_engine.py` line 70, replace `datetime.now(IST).isoformat()` with `event.order_timestamp or datetime.now(IST).isoformat()`.

---

## Sub-Task 2 — Expose `time_to_market_open_seconds` and pending-queue count in the preflight API

**Status:** [ ] pending

**Intent**
The frontend needs a backend signal for how many seconds remain until 09:15:00 and how many orders are currently queued. This lets the UI display the countdown without the frontend having to hard-code 09:15:00.

**Relevant Context**
- `backend/models/schemas.py` lines 167–171 — `PreflightResponse` model; add `time_to_market_open_seconds: int` and `pending_orders_count: int`
- `backend/api/routes.py` lines 34–43 — `preflight()` endpoint; compute both new fields using existing `state_manager.get_pending_orders_count()` (already used in `_countdown_loop`) and the same market-open arithmetic from `_countdown_loop` (`jobs.py` line 96–97)
- `backend/scheduler/jobs.py` lines 92–97 — reference implementation for remaining-seconds calculation

**Expected Outcomes**
- `GET /health/preflight` response includes `time_to_market_open_seconds` (0 if past 09:15) and `pending_orders_count`.
- No new endpoint needed; existing preflight polling by the frontend receives the data.

**Todo List**
1. In `backend/models/schemas.py`, add `time_to_market_open_seconds: int` and `pending_orders_count: int` to `PreflightResponse`.
2. In `backend/api/routes.py` → `preflight()`, add:
   - Compute market-open remaining seconds (0 if past 09:15:00 IST today).
   - Fetch `pending_count = await state_manager.get_pending_orders_count()`.
   - Populate both new fields in the returned `PreflightResponse`.
3. In `frontend/src/types.ts` (or wherever `PreflightStatus` is declared), add `time_to_market_open_seconds: number` and `pending_orders_count: number`.

---

## Sub-Task 3 — Show countdown and pending-orders count in the Preflight UI

**Status:** [ ] pending

**Intent**
Once the backend sends `time_to_market_open_seconds` and `pending_orders_count`, the Preflight section should render them so the user can see "Orders fire in 47s" and "3 orders queued" instead of a blank screen.

**Relevant Context**
- `frontend/src/App.tsx` lines 529–535 — Preflight `<div className="preflight-row">` with `<Metric>` components; add two new `<Metric>` tiles here
- The existing `<Metric label="Next auto-scan in" value=.../>` pattern is the model to follow
- Only show the countdown tile when `time_to_market_open_seconds > 0` (i.e., before market open)
- Only show the pending-orders tile when `pending_orders_count > 0`

**Expected Outcomes**
- Between 09:08 and 09:15, the Preflight row shows "Market open in Xs" and "X orders queued".
- After 09:15 both tiles disappear (values are 0 / data-driven hide).

**Todo List**
1. In `frontend/src/App.tsx`, add two conditional `<Metric>` tiles to the preflight row:
   - `time_to_market_open_seconds > 0` → `<Metric label="Market open in" value={`${time_to_market_open_seconds}s`} />`
   - `pending_orders_count > 0` → `<Metric label="Orders queued" value={String(pending_orders_count)} />`
