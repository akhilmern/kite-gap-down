from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from backend.config.settings import get_settings

logger = logging.getLogger(__name__)

INSTRUMENTS_CACHE = Path("backend/data/kite_nse_equity.json")
INSTRUMENTS_CSV_URL = "https://api.kite.trade/instruments"


def _checksum(api_key: str, request_token: str, api_secret: str) -> str:
    raw = f"{api_key}{request_token}{api_secret}"
    return hashlib.sha256(raw.encode()).hexdigest()


class KiteClient:
    """Async Kite Connect REST client."""

    def __init__(self, access_token: Optional[str] = None) -> None:
        self._access_token = access_token

    @property
    def access_token(self) -> Optional[str]:
        return self._access_token

    @access_token.setter
    def access_token(self, value: str) -> None:
        self._access_token = value

    def _headers(self) -> Dict[str, str]:
        rs = get_settings()
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {rs.kite_api_key}:{self._access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def build_login_url(self) -> str:
        rs = get_settings()
        return (
            f"https://kite.zerodha.com/connect/login"
            f"?api_key={rs.kite_api_key}&v=3"
        )

    async def generate_session(self, request_token: str) -> Dict[str, Any]:
        rs = get_settings()
        checksum = _checksum(rs.kite_api_key, request_token, rs.kite_api_secret)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{rs.kite_api_base}/session/token",
                data={
                    "api_key": rs.kite_api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
                headers={"X-Kite-Version": "3"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", data)

    async def _get(self, path: str, params: Optional[Dict] = None) -> Any:
        rs = get_settings()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{rs.kite_api_base}{path}",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("data", resp.json())

    async def _post(self, path: str, data: Dict) -> Any:
        rs = get_settings()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{rs.kite_api_base}{path}",
                data=data,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("data", resp.json())

    async def _delete(self, path: str, params: Optional[Dict] = None) -> Any:
        rs = get_settings()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.delete(
                f"{rs.kite_api_base}{path}",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json().get("data", resp.json())

    # ------------------------------------------------------------------
    # Quotes
    # ------------------------------------------------------------------

    async def get_quote(self, instruments: List[str]) -> Dict[str, Any]:
        """Fetch full quote for instruments like ['NSE:RELIANCE', ...]."""
        # Max 500 per request
        result = {}
        for i in range(0, len(instruments), 500):
            batch = instruments[i : i + 500]
            data = await self._get("/quote", params={"i": batch})
            result.update(data)
        return result

    async def get_ltp(self, instruments: List[str]) -> Dict[str, Any]:
        result = {}
        for i in range(0, len(instruments), 500):
            batch = instruments[i : i + 500]
            data = await self._get("/quote/ltp", params={"i": batch})
            result.update(data)
        return result

    async def get_ohlc(self, instruments: List[str]) -> Dict[str, Any]:
        result = {}
        for i in range(0, len(instruments), 500):
            batch = instruments[i : i + 500]
            data = await self._get("/quote/ohlc", params={"i": batch})
            result.update(data)
        return result

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    async def get_historical(
        self,
        instrument_token: int,
        interval: str,
        from_date: str,
        to_date: str,
        continuous: bool = False,
    ) -> List[Any]:
        path = f"/instruments/historical/{instrument_token}/{interval}"
        data = await self._get(
            path,
            params={
                "from": from_date,
                "to": to_date,
                "continuous": 1 if continuous else 0,
            },
        )
        return data.get("candles", [])

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def place_order(self, variety: str, order_data: Dict) -> str:
        """Place order and return order_id."""
        rs = get_settings()
        retries = rs.max_order_placement_retries
        backoff = rs.retry_backoff_ms / 1000.0
        last_err: Exception = Exception("no attempt")
        for attempt in range(retries):
            try:
                result = await self._post(f"/orders/{variety}", order_data)
                oid = result.get("order_id") if isinstance(result, dict) else result
                logger.info("Order placed: %s attempt=%d", oid, attempt + 1)
                return str(oid)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 403:
                    raise
                last_err = exc
                logger.warning("Order attempt %d failed: %s", attempt + 1, exc)
            except Exception as exc:
                last_err = exc
                logger.warning("Order attempt %d error: %s", attempt + 1, exc)
            await asyncio.sleep(backoff * (2 ** attempt))
        raise last_err

    async def cancel_order(self, variety: str, order_id: str) -> None:
        await self._delete(f"/orders/{variety}/{order_id}")

    async def get_orders(self) -> List[Dict]:
        return await self._get("/orders") or []

    async def get_order_history(self, order_id: str) -> List[Dict]:
        return await self._get(f"/orders/{order_id}") or []

    async def get_positions(self) -> Dict[str, Any]:
        return await self._get("/portfolio/positions") or {}

    async def get_holdings(self) -> List[Dict]:
        return await self._get("/portfolio/holdings") or []

    async def get_profile(self) -> Dict[str, Any]:
        return await self._get("/user/profile") or {}

    # ------------------------------------------------------------------
    # Instrument master
    # ------------------------------------------------------------------

    async def refresh_instruments(self) -> int:
        """Download Kite instrument master CSV and cache NSE EQ instruments."""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(INSTRUMENTS_CSV_URL)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
        if not lines:
            raise ValueError("Empty instrument CSV")
        header = lines[0].split(",")
        instruments: Dict[str, Any] = {}
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < len(header):
                continue
            row = dict(zip(header, parts))
            if row.get("exchange") == "NSE" and row.get("instrument_type") == "EQ":
                sym = row.get("tradingsymbol", "")
                if sym:
                    instruments[sym] = {
                        "instrument_token": int(row.get("instrument_token", 0)),
                        "tradingsymbol": sym,
                        "exchange": "NSE",
                        "name": row.get("name", ""),
                        "expiry": row.get("expiry", ""),
                        "tick_size": float(row.get("tick_size", 0.05)),
                        "lot_size": int(row.get("lot_size", 1)),
                        "instrument_type": "EQ",
                        "segment": row.get("segment", ""),
                        "exchange_token": row.get("exchange_token", ""),
                        # Fields to be enriched later
                        "prev_close": None,
                        "vol_history": [],
                        "sector": None,
                        "market_cap": None,
                    }
        INSTRUMENTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(INSTRUMENTS_CACHE, "w") as f:
            json.dump(instruments, f)
        logger.info("Cached %d NSE EQ instruments", len(instruments))
        return len(instruments)

    def load_instruments_cache(self) -> Dict[str, Any]:
        if not INSTRUMENTS_CACHE.exists():
            return {}
        with open(INSTRUMENTS_CACHE, "r") as f:
            return json.load(f)

    def save_instruments_cache(self, data: Dict[str, Any]) -> None:
        INSTRUMENTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(INSTRUMENTS_CACHE, "w") as f:
            json.dump(data, f)

    async def fetch_and_store_prev_close(self) -> int:
        """Fetch previous close for all cached instruments via OHLC endpoint."""
        cache = self.load_instruments_cache()
        if not cache:
            logger.warning("No instrument cache — run refresh_instruments first")
            return 0
        symbols = list(cache.keys())
        logger.info("Fetching prev close for %d instruments…", len(symbols))
        updated = 0
        batch_size = 500
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            instruments = [f"NSE:{s}" for s in batch]
            try:
                data = await self.get_ohlc(instruments)
                for key, val in data.items():
                    sym = key.replace("NSE:", "")
                    if sym in cache:
                        ohlc = val.get("ohlc", {})
                        cache[sym]["prev_close"] = ohlc.get("close")
                        updated += 1
            except Exception as exc:
                logger.error("Prev close batch error: %s", exc)
        self.save_instruments_cache(cache)
        logger.info("Prev close updated for %d instruments", updated)
        return updated

    async def fetch_and_store_vol_history(self) -> int:
        """Fetch 20-day volume history for all cached instruments."""
        from datetime import date, timedelta
        cache = self.load_instruments_cache()
        if not cache:
            return 0
        to_dt = date.today().strftime("%Y-%m-%d")
        from_dt = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        symbols = list(cache.keys())
        updated = 0
        sem = asyncio.Semaphore(5)

        async def _fetch_one(sym: str) -> None:
            nonlocal updated
            token = cache[sym].get("instrument_token")
            if not token:
                return
            async with sem:
                try:
                    candles = await self.get_historical(
                        token, "day", from_dt, to_dt
                    )
                    volumes = [int(c[5]) for c in candles if len(c) > 5][-20:]
                    cache[sym]["vol_history"] = volumes
                    updated += 1
                except Exception as exc:
                    logger.debug("Vol history %s: %s", sym, exc)

        tasks = [_fetch_one(s) for s in symbols]
        logger.info("Fetching vol history for %d instruments…", len(tasks))
        await asyncio.gather(*tasks)
        self.save_instruments_cache(cache)
        logger.info("Vol history updated for %d instruments", updated)
        return updated


# Shared client instance
kite_client = KiteClient()
