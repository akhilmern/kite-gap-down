from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from config.settings import DATA_DIR, settings
from models.schemas import KiteOrderRequest, KiteOrderResult, OrderEvent
from models.state import state_manager

logger = logging.getLogger(__name__)

INSTRUMENT_CACHE = DATA_DIR / "kite_nse_instruments.json"
# DATA_DIR = backend/data  →  .parent = backend/  →  .parent = project root
ENV_FILE = DATA_DIR.parent.parent / ".env"

# Kite Connect API base
KITE_API_BASE = "https://api.kite.trade"
KITE_LOGIN_BASE = "https://kite.zerodha.com/connect"


class KiteClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=20.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        require_auth: bool = True,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_headers = {
            "X-Kite-Version": "3",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if headers:
            request_headers.update(headers)
        if require_auth:
            if not state_manager.access_token:
                raise RuntimeError("Kite access token is not available")
            request_headers["Authorization"] = f"token {settings.kite_api_key}:{state_manager.access_token}"
        response = await self._client.request(
            method,
            url,
            headers=request_headers,
            params=params,
            data=data,
            json=json_body,
            timeout=timeout,
        )
        if response.is_error:
            logger.error(
                "kite_api_error method=%s url=%s status=%s body=%s",
                method,
                url,
                response.status_code,
                response.text,
            )
            response.raise_for_status()
        if not response.content:
            return {}
        body = response.json()
        # Kite wraps response: {"status": "success", "data": {...}}
        if isinstance(body, dict) and body.get("status") == "error":
            raise RuntimeError(f"Kite API error: {body.get('message', body)}")
        return body

    def build_login_url(self, state: str = "gapdown") -> str:
        query = urlencode(
            {
                "api_key": settings.kite_api_key,
                "v": "3",
            }
        )
        return f"{KITE_LOGIN_BASE}/login?{query}"

    async def exchange_code_for_token(self, request_token: str) -> dict[str, Any]:
        """
        Exchange the request_token (returned by Kite after login) for an
        access_token using the api_key + api_secret checksum method.
        """
        import hashlib
        checksum = hashlib.sha256(
            f"{settings.kite_api_key}{request_token}{settings.kite_api_secret}".encode()
        ).hexdigest()
        payload = {
            "api_key": settings.kite_api_key,
            "request_token": request_token,
            "checksum": checksum,
        }
        body = await self._request(
            "POST",
            f"{KITE_API_BASE}/session/token",
            data=payload,
            require_auth=False,
        )
        return body.get("data") or body

    async def get_profile(self) -> dict[str, Any]:
        body = await self._request("GET", f"{KITE_API_BASE}/user/profile")
        return body.get("data") or body

    async def invalidate_token(self) -> None:
        """Invalidate (logout) the current access token."""
        try:
            await self._request(
                "DELETE",
                f"{KITE_API_BASE}/session/token",
                params={"api_key": settings.kite_api_key, "access_token": state_manager.access_token},
            )
        except Exception:  # noqa: BLE001
            pass

    async def get_order_book(self) -> list[dict[str, Any]]:
        body = await self._request("GET", f"{KITE_API_BASE}/orders")
        return body.get("data") or []

    async def get_order_details(self, order_id: str) -> list[dict[str, Any]]:
        body = await self._request("GET", f"{KITE_API_BASE}/orders/{order_id}")
        return body.get("data") or []

    async def place_order(self, order: KiteOrderRequest) -> KiteOrderResult:
        started = time.perf_counter()
        body: dict[str, Any] = {
            "exchange": order.exchange,
            "tradingsymbol": order.tradingsymbol,
            "transaction_type": order.transaction_type,
            "quantity": order.quantity,
            "product": order.product,
            "order_type": order.order_type,
            "validity": order.validity,
        }
        if order.price and order.price != 0:
            body["price"] = round(float(order.price), 2)
        if order.trigger_price and order.trigger_price != 0:
            body["trigger_price"] = round(float(order.trigger_price), 2)
        if order.disclosed_quantity:
            body["disclosed_quantity"] = int(order.disclosed_quantity)
        if order.tag:
            body["tag"] = order.tag[:20]  # Kite tag max 20 chars

        logger.debug("place_order_body symbol=%s body=%s", order.tradingsymbol, body)
        payload = await self._request(
            "POST",
            f"{KITE_API_BASE}/orders/{order.variety}",
            data=body,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        data = payload.get("data") or {}
        order_id_val = data.get("order_id") or ""
        order_ids = [str(order_id_val)] if order_id_val else []
        logger.info(
            "order_place symbol=%s qty=%s price=%s order_id=%s latency_ms=%.2f",
            order.tradingsymbol,
            order.quantity,
            order.price,
            ",".join(order_ids),
            latency_ms,
        )
        return KiteOrderResult(order_ids=order_ids, latency_ms=latency_ms, raw=payload)

    async def cancel_order(self, order_id: str, variety: str = "regular") -> dict[str, Any]:
        body = await self._request(
            "DELETE",
            f"{KITE_API_BASE}/orders/{variety}/{order_id}",
        )
        return body.get("data") or {}

    async def get_ohlc_quotes(self, instrument_keys: list[str]) -> dict[str, Any]:
        """
        Fetch OHLC data for a list of instruments in 'EXCHANGE:SYMBOL' format.
        Returns dict keyed by 'EXCHANGE:SYMBOL'.
        """
        params = {"i": instrument_keys}
        body = await self._request(
            "GET",
            f"{KITE_API_BASE}/quote/ohlc",
            params=params,
            timeout=settings.scanner_timeout_seconds,
        )
        return body.get("data") or {}

    async def get_full_quotes(self, instrument_keys: list[str]) -> dict[str, Any]:
        """
        Fetch full market quotes (including depth / bid-ask) for up to 500 keys.
        instrument_keys in 'EXCHANGE:SYMBOL' format.
        Returns the data dict keyed by 'EXCHANGE:SYMBOL'.
        """
        params = {"i": instrument_keys}
        body = await self._request(
            "GET",
            f"{KITE_API_BASE}/quote",
            params=params,
            timeout=settings.scanner_timeout_seconds,
        )
        return body.get("data") or {}

    async def get_positions(self) -> list[dict[str, Any]]:
        """Returns day + net positions from Kite."""
        body = await self._request("GET", f"{KITE_API_BASE}/portfolio/positions")
        data = body.get("data") or {}
        # Kite returns {"net": [...], "day": [...]}
        return data.get("day") or data.get("net") or []

    async def _fetch_daily_volumes_raw(
        self,
        instrument_token: int,
        days: int = 22,
    ) -> list[int]:
        """
        Fetch daily volumes from Kite historical candle API.
        Returns up to *days* completed session volumes (oldest-first),
        dropping today's in-progress candle.
        """
        from datetime import date, timedelta

        to_date = date.today().isoformat()
        from_date = (date.today() - timedelta(days=days * 2)).isoformat()
        try:
            body = await self._request(
                "GET",
                f"{KITE_API_BASE}/instruments/historical/{instrument_token}/day",
                params={"from": from_date, "to": to_date},
                timeout=10.0,
            )
            candles = (body.get("data") or {}).get("candles") or []
            # Each candle: [date, open, high, low, close, volume, oi]
            # candles are oldest-first; last entry may be today's partial session
            volumes = [int(c[5]) for c in candles if len(c) > 5 and c[5]]
            if volumes:
                volumes = volumes[:-1]  # drop today's incomplete session
            return volumes[-days:]
        except Exception:  # noqa: BLE001
            return []

    async def fetch_and_store_vol_history(self, days: int = 20) -> int:
        """
        Fetch the last *days* completed daily volumes for every NSE EQ instrument
        and persist them into the instrument cache under the ``vol_history`` key.
        """
        all_instruments = await self.load_instruments(force_refresh=False)
        eq_instruments = [
            i for i in all_instruments
            if i.get("instrument_type") == "EQ" and i.get("instrument_token")
        ]

        semaphore = asyncio.Semaphore(settings.scanner_concurrency)

        async def fetch_one_safe(instrument: dict[str, Any]) -> bool:
            token = instrument["instrument_token"]
            async with semaphore:
                vols = await self._fetch_daily_volumes_raw(int(token), days=days)
            if vols:
                instrument["vol_history"] = vols
                return True
            return False

        results = await asyncio.gather(*(fetch_one_safe(i) for i in eq_instruments))
        updated = sum(1 for r in results if r)

        # Persist — rebuild full list keeping non-EQ instruments unchanged
        eq_set = {i["instrument_token"] for i in eq_instruments}
        non_eq = [i for i in all_instruments if i["instrument_token"] not in eq_set]
        merged = non_eq + eq_instruments
        INSTRUMENT_CACHE.write_text(json.dumps(merged))
        logger.info(
            "fetch_vol_history: updated %d / %d EQ instruments",
            updated,
            len(eq_instruments),
        )
        return updated

    async def fetch_and_store_prev_close(self) -> int:
        """
        Fetch yesterday's closing price for every EQ instrument and persist it
        into the instrument cache (adds/updates the ``prev_close`` field).
        Uses the Kite OHLC endpoint — ``last_price`` is today's price,
        ``ohlc.close`` is the previous session close.
        """
        all_instruments = await self.load_instruments(force_refresh=False)
        eq_instruments = [
            i for i in all_instruments
            if i.get("instrument_type") == "EQ"
            and i.get("tradingsymbol")
            and i.get("exchange") == "NSE"
        ]

        # Build instrument_key → instrument map using NSE:SYMBOL format
        key_map: dict[str, dict[str, Any]] = {
            f"NSE:{i['tradingsymbol']}": i for i in eq_instruments
        }
        keys = list(key_map.keys())

        batch_size = settings.scanner_batch_size
        semaphore = asyncio.Semaphore(settings.scanner_concurrency)
        updated = 0
        unmatched = 0

        async def fetch_batch(batch_keys: list[str]) -> None:
            nonlocal updated, unmatched
            for attempt in range(settings.scanner_retries):
                try:
                    async with semaphore:
                        quotes = await self.get_ohlc_quotes(batch_keys)
                    for raw_key, quote in quotes.items():
                        instrument = key_map.get(raw_key)
                        if instrument is None:
                            unmatched += 1
                            continue
                        ohlc = quote.get("ohlc") or {}
                        # Kite OHLC: ohlc.close = previous session close
                        prev_close = self._to_float(ohlc.get("close"))
                        if prev_close and prev_close > 0:
                            instrument["prev_close"] = round(prev_close, 2)
                            updated += 1
                    return
                except Exception as exc:  # noqa: BLE001
                    if attempt == settings.scanner_retries - 1:
                        logger.error("fetch_prev_close_batch_failed size=%d: %s", len(batch_keys), exc)
                    else:
                        await asyncio.sleep(2 ** attempt)

        batches = [keys[i: i + batch_size] for i in range(0, len(keys), batch_size)]
        await asyncio.gather(*(fetch_batch(b) for b in batches))

        # Persist
        eq_set = {i["tradingsymbol"] for i in eq_instruments}
        non_eq = [i for i in all_instruments if i.get("tradingsymbol") not in eq_set or i.get("exchange") != "NSE"]
        merged = non_eq + eq_instruments
        INSTRUMENT_CACHE.write_text(json.dumps(merged))
        logger.info(
            "fetch_prev_close: updated %d / %d EQ instruments (unmatched=%d)",
            updated,
            len(eq_instruments),
            unmatched,
        )
        return updated

    async def load_instruments(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if INSTRUMENT_CACHE.exists() and not force_refresh:
            return json.loads(INSTRUMENT_CACHE.read_text())
        return await self.fetch_and_filter_intraday_eligible()

    async def fetch_and_filter_intraday_eligible(self) -> list[dict[str, Any]]:
        """
        Fetch the Kite NSE instrument master CSV, filter to only EQ instruments
        that are intraday-eligible (exchange=NSE, instrument_type=EQ).
        Excludes BE, BT, SME, etc. series that don't support MIS orders.

        Existing per-instrument data (prev_close, vol_history) stored in cache
        is preserved for instruments that remain in the list.
        """
        response = await self._client.get(
            "https://api.kite.trade/instruments/NSE",
            timeout=30.0,
        )
        response.raise_for_status()

        # Kite instruments CSV: instrument_token,exchange_token,tradingsymbol,name,
        # last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange
        reader = csv.DictReader(io.StringIO(response.text))
        live_instruments: list[dict[str, Any]] = []
        for row in reader:
            live_instruments.append(dict(row))

        # Filter intraday-eligible: NSE EQ normal series (not SME, not BE series)
        # Kite EQ instruments have instrument_type=EQ and segment=NSE (not NSE-SME etc.)
        intraday: list[dict[str, Any]] = [
            item for item in live_instruments
            if item.get("instrument_type") == "EQ"
            and item.get("exchange") == "NSE"
            and item.get("segment") == "NSE"
        ]

        # Build lookup set
        intraday_tokens: set[str] = {i["instrument_token"] for i in intraday}

        # Load existing cache to preserve enriched fields
        cached_by_token: dict[str, dict[str, Any]] = {}
        if INSTRUMENT_CACHE.exists():
            try:
                for inst in json.loads(INSTRUMENT_CACHE.read_text()):
                    cached_by_token[str(inst.get("instrument_token", ""))] = inst
            except Exception:  # noqa: BLE001
                pass

        enriched_fields = ("prev_close", "vol_history")
        result: list[dict[str, Any]] = []
        for item in intraday:
            token = item["instrument_token"]
            merged = dict(item)
            if token in cached_by_token:
                for field in enriched_fields:
                    if field in cached_by_token[token]:
                        merged[field] = cached_by_token[token][field]
            result.append(merged)

        prev_count = len(cached_by_token)
        new_count = len(result)
        added = len(intraday_tokens - set(cached_by_token))
        removed = len(set(cached_by_token) - intraday_tokens)
        logger.info(
            "fetch_and_filter_intraday_eligible: %d → %d instruments "
            "(+%d added, -%d removed as non-intraday-eligible)",
            prev_count,
            new_count,
            added,
            removed,
        )

        INSTRUMENT_CACHE.write_text(json.dumps(result))
        return result

    async def write_env_settings(self, entries: dict[str, Any]) -> None:
        if not settings.write_env_from_ui:
            return
        current: dict[str, str] = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                current[key.strip()] = value.strip()
        for key, value in entries.items():
            current[key] = self._format_env_value(value)
        ordered = "\n".join(f"{key}={value}" for key, value in sorted(current.items())) + "\n"
        ENV_FILE.write_text(ordered)

    def _format_env_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return json.dumps(value)
        return str(value)

    def normalize_order_event(self, raw_event: dict[str, Any]) -> OrderEvent | None:
        """
        Normalise a Kite order-update event (from KiteTicker on_order_update
        or from the REST orders endpoint) into a unified OrderEvent.

        Kite order fields: order_id, status, transaction_type, tradingsymbol,
        instrument_token, average_price, filled_quantity, product, tag,
        parent_order_id, order_type, status_message, order_timestamp.
        """
        if not isinstance(raw_event, dict):
            return None

        # Kite uses numeric instrument_token; convert to NSE:SYMBOL key format
        tradingsymbol = raw_event.get("tradingsymbol") or raw_event.get("trading_symbol")
        exchange = raw_event.get("exchange") or "NSE"
        instrument_token_num = raw_event.get("instrument_token")
        # Build a string key consistent with our instrument map: "NSE:SYMBOL"
        instrument_token = f"{exchange}:{tradingsymbol}" if tradingsymbol else (
            str(instrument_token_num) if instrument_token_num else None
        )

        return OrderEvent(
            order_id=str(raw_event.get("order_id") or ""),
            status=str(raw_event.get("status") or "UNKNOWN"),
            transaction_type=raw_event.get("transaction_type"),
            tradingsymbol=tradingsymbol,
            instrument_token=instrument_token,
            average_price=self._to_float(raw_event.get("average_price")),
            filled_quantity=self._to_int(raw_event.get("filled_quantity")),
            product=raw_event.get("product"),
            source=raw_event.get("tag") or raw_event.get("placed_by"),
            parent_order_id=raw_event.get("parent_order_id"),
            order_type=raw_event.get("order_type"),
            status_message=raw_event.get("status_message"),
            order_timestamp=(
                raw_event.get("order_timestamp")
                or raw_event.get("exchange_update_timestamp")
                or raw_event.get("exchange_timestamp")
            ),
            raw=raw_event,
        )

    def normalize_order_book_event(self, payload: dict[str, Any]) -> OrderEvent:
        return self.normalize_order_event(payload) or OrderEvent(
            order_id=str(payload.get("order_id") or ""),
            status="UNKNOWN",
            raw=payload,
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


kite_client = KiteClient()
