from __future__ import annotations

import asyncio
import gzip
import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from config.settings import DATA_DIR, settings
from models.schemas import OrderEvent, UpstoxOrderRequest, UpstoxOrderResult
from models.state import state_manager

logger = logging.getLogger(__name__)

INSTRUMENT_CACHE = DATA_DIR / "upstox_nse_equity_instruments.json"
# DATA_DIR = backend/data  →  .parent = backend/  →  .parent = project root
ENV_FILE = DATA_DIR.parent.parent / ".env"


class UpstoxClient:
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
        request_headers = {"Accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if require_auth:
            if not state_manager.access_token:
                raise RuntimeError("Upstox access token is not available")
            request_headers["Authorization"] = f"Bearer {state_manager.access_token}"
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
                "upstox_api_error method=%s url=%s status=%s body=%s",
                method,
                url,
                response.status_code,
                response.text,
            )
            response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def build_login_url(self, state: str = "gapdown") -> str:
        query = urlencode(
            {
                "response_type": "code",
                "client_id": settings.upstox_client_id,
                "redirect_uri": settings.upstox_redirect_uri,
                "state": state,
            }
        )
        return f"{settings.upstox_api_base}/v2/login/authorization/dialog?{query}"

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        payload = {
            "code": code,
            "client_id": settings.upstox_client_id,
            "client_secret": settings.upstox_client_secret,
            "redirect_uri": settings.upstox_redirect_uri,
            "grant_type": "authorization_code",
        }
        return await self._request(
            "POST",
            f"{settings.upstox_api_base}/v2/login/authorization/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=payload,
            require_auth=False,
        )

    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", f"{settings.upstox_api_base}/v2/user/profile")

    async def authorize_portfolio_feed(self) -> str:
        payload = await self._request(
            "GET",
            f"{settings.upstox_api_base}/v2/feed/portfolio-stream-feed/authorize",
            params={"update_types": "order,position,holding"},
        )
        data = payload.get("data") or {}
        return data.get("authorized_redirect_uri", "")

    async def get_order_book(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", f"{settings.upstox_api_base}/v2/order/retrieve-all")
        return payload.get("data") or []

    async def get_order_details(self, order_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"{settings.upstox_api_base}/v2/order/details",
            params={"order_id": order_id},
        )
        return payload.get("data") or {}

    async def place_order(self, order: UpstoxOrderRequest) -> UpstoxOrderResult:
        started = time.perf_counter()
        # Build body: exclude None (e.g. tag when not set), but keep all numeric
        # fields even when zero — v3 requires disclosed_quantity, trigger_price,
        # price as explicit values. Ensure price fields are floats, not ints.
        body = order.model_dump(exclude_none=True)
        body["price"] = float(body.get("price", 0))
        body["trigger_price"] = float(body.get("trigger_price", 0))
        body["disclosed_quantity"] = int(body.get("disclosed_quantity", 0))
        logger.debug("place_order_body symbol=%s body=%s", order.instrument_token, body)
        payload = await self._request(
            "POST",
            f"{settings.upstox_hft_api_base}/v3/order/place",
            headers={"Content-Type": "application/json"},
            json_body=body,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        data = payload.get("data") or {}
        order_ids = data.get("order_ids") or []
        if isinstance(order_ids, str):
            order_ids = [order_ids]
        logger.info(
            "order_place symbol=%s qty=%s price=%s order_id=%s latency_ms=%.2f",
            order.instrument_token,
            order.quantity,
            order.price,
            ",".join(order_ids),
            latency_ms,
        )
        return UpstoxOrderResult(order_ids=order_ids, latency_ms=latency_ms, raw=payload)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"{settings.upstox_hft_api_base}/v3/order/cancel",
            params={"order_id": order_id},
        )

    async def _fetch_daily_volumes_raw(
        self,
        instrument_key: str,
        days: int = 22,
    ) -> list[int]:
        """
        Fetch daily volumes from Upstox historical candle API.
        Returns up to *days* completed session volumes (newest-first then
        reversed to oldest-first), dropping today's in-progress candle.
        Returns an empty list on any error.
        """
        from datetime import date, timedelta

        to_date = date.today().isoformat()
        from_date = (date.today() - timedelta(days=days * 2)).isoformat()
        try:
            payload = await self._request(
                "GET",
                f"{settings.upstox_api_base}/v2/historical-candle/{instrument_key}/day/{to_date}/{from_date}",
                timeout=10.0,
            )
            candles = (payload.get("data") or {}).get("candles") or []
            # Each candle: [timestamp, open, high, low, close, volume, oi]
            # candles are newest-first; first entry may be today's partial session
            volumes = [int(c[5]) for c in candles if len(c) > 5 and c[5]]
            if volumes:
                volumes = volumes[1:]  # drop today's incomplete session
            return volumes[:days]
        except Exception:  # noqa: BLE001
            return []

    async def fetch_and_store_vol_history(self, days: int = 20) -> int:
        """
        Fetch the last *days* completed daily volumes for every NSE EQ instrument
        and persist them into the instrument cache under the ``vol_history`` key.

        Designed to be called once before market open (via the UI button), so
        the scanner can compute volume-spike ratios instantly at scan time without
        making any extra API calls.

        Returns the number of instruments updated.
        """
        all_instruments = await self.load_instruments(force_refresh=False)
        eq_instruments = [
            i for i in all_instruments
            if i.get("instrument_type") == "EQ" and i.get("instrument_key")
        ]

        semaphore = asyncio.Semaphore(settings.scanner_concurrency)

        async def fetch_one_safe(instrument: dict[str, Any]) -> bool:
            key = instrument["instrument_key"]
            async with semaphore:
                vols = await self._fetch_daily_volumes_raw(key, days=days)
            if vols:
                instrument["vol_history"] = vols
                return True
            return False

        results = await asyncio.gather(*(fetch_one_safe(i) for i in eq_instruments))
        updated = sum(1 for r in results if r)

        # Persist — rebuild full list keeping non-EQ instruments unchanged
        eq_set = {i["instrument_key"] for i in eq_instruments}
        non_eq = [i for i in all_instruments if i["instrument_key"] not in eq_set]
        merged = non_eq + eq_instruments
        INSTRUMENT_CACHE.write_text(json.dumps(merged))
        logger.info(
            "fetch_vol_history: updated %d / %d EQ instruments",
            updated,
            len(eq_instruments),
        )
        return updated

    async def get_ohlc_quotes(self, instrument_keys: list[str]) -> dict[str, Any]:
        params = {"instrument_key": ",".join(instrument_keys), "interval": "1d"}
        payload = await self._request(
            "GET",
            f"{settings.upstox_api_base}/v2/market-quote/ohlc",
            params=params,
            timeout=settings.scanner_timeout_seconds,
        )
        return payload.get("data") or {}

    async def get_full_quotes(self, instrument_keys: list[str]) -> dict[str, Any]:
        """
        Fetch full market quotes (including depth / bid-ask) for up to 500 keys.
        Returns the ``data`` dict keyed by trading symbol (e.g. ``NSE_EQ:SBIN``).
        Each entry contains a ``depth`` field with ``buy`` and ``sell`` lists of
        {``quantity``, ``price``, ``orders``}.  During pre-open this reflects
        the pre-open order book totals.
        """
        params = {"instrument_key": ",".join(instrument_keys)}
        payload = await self._request(
            "GET",
            f"{settings.upstox_api_base}/v2/market-quote/quotes",
            params=params,
            timeout=settings.scanner_timeout_seconds,
        )
        return payload.get("data") or {}

    async def get_upstox_positions(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", f"{settings.upstox_api_base}/v2/portfolio/short-term-positions")
        return payload.get("data") or []

    async def load_instruments(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if INSTRUMENT_CACHE.exists() and not force_refresh:
            return json.loads(INSTRUMENT_CACHE.read_text())
        return await self.fetch_and_filter_intraday_eligible()

    async def fetch_and_filter_intraday_eligible(self) -> list[dict[str, Any]]:
        """
        Fetch the live Upstox NSE instrument master, cross-reference it against
        the local cache, and persist only stocks confirmed as intraday-eligible
        (``instrument_type == "EQ"`` on NSE — the Normal group, MIS-tradeable).

        Non-EQ types such as ``BE`` (Book Entry / trade-to-trade),
        ``SM`` (SME), ``SG`` (sovereign gold/govt securities), ``TB``
        (treasury bills) and various bond series are **excluded** because
        Upstox does not allow MIS/intraday orders for them.

        Existing per-instrument data (``prev_close``, ``vol_history``, …) that
        was previously enriched into the cache is preserved for instruments that
        remain in the list.

        Returns the filtered list and writes it to ``INSTRUMENT_CACHE``.
        """
        response = await self._client.get(
            "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
            timeout=30.0,
        )
        response.raise_for_status()
        live_instruments: list[dict[str, Any]] = json.loads(
            gzip.decompress(response.content).decode("utf-8")
        )

        # Build a set of instrument keys confirmed as intraday-eligible (EQ, non-MF)
        intraday_keys: set[str] = {
            item["instrument_key"]
            for item in live_instruments
            if str(item.get("instrument_key", "")).startswith("NSE_EQ|")
            and item.get("instrument_type") == "EQ"
            and not str(item.get("isin", "")).startswith("INF")
        }

        # Load existing cache so we can preserve enriched fields (prev_close, vol_history)
        cached_by_key: dict[str, dict[str, Any]] = {}
        if INSTRUMENT_CACHE.exists():
            try:
                for inst in json.loads(INSTRUMENT_CACHE.read_text()):
                    cached_by_key[inst["instrument_key"]] = inst
            except Exception:  # noqa: BLE001
                pass

        # Build a lookup of live EQ records (provides fresh base fields)
        live_by_key: dict[str, dict[str, Any]] = {
            item["instrument_key"]: item
            for item in live_instruments
            if item.get("instrument_key") in intraday_keys
        }

        # Merge: start from live record (fresh base), overlay cached enriched fields
        enriched_fields = ("prev_close", "vol_history")
        result: list[dict[str, Any]] = []
        for key, live_rec in live_by_key.items():
            merged = dict(live_rec)
            if key in cached_by_key:
                for field in enriched_fields:
                    if field in cached_by_key[key]:
                        merged[field] = cached_by_key[key][field]
            result.append(merged)

        prev_count = len(cached_by_key)
        new_count = len(result)
        added = len(intraday_keys - set(cached_by_key))
        removed = len(set(cached_by_key) - intraday_keys)
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

    async def fetch_and_store_prev_close(self) -> int:
        """
        Fetch yesterday's closing price for every EQ instrument and persist it
        into the instrument cache (adds/updates the ``prev_close`` field).

        Uses the OHLC ``1d`` endpoint — ``prev_ohlc.close`` is the previous
        session's close.  This is called once before the scan (via the scheduler
        or the "Fetch prev close" button) so the scanner never depends on
        ``prev_ohlc`` being present in the live scan response.

        Returns the number of instruments updated.
        """
        all_instruments = await self.load_instruments(force_refresh=False)
        eq_instruments = [
            i for i in all_instruments
            if i.get("instrument_type") == "EQ"
            and i.get("instrument_key")
            and i.get("exchange_token")
        ]

        # Upstox's instrument_key format is ISIN-based everywhere in the API
        # (e.g. "NSE_EQ|INE848E01016"), and the instrument master file already
        # gives us that correct key on every instrument. Previously this code
        # reconstructed a synthetic "NSE_EQ|<exchange_token>" key instead —
        # that is not a valid instrument_key, so the OHLC endpoint was very
        # likely returning an empty (or near-empty) data dict for those
        # requests, which is why nothing ever got updated. Use the real
        # instrument_key directly instead.
        #
        # The OHLC response's top-level `data` dict is keyed by trading
        # symbol (e.g. "NSE_EQ:NHPC"), NOT by instrument_key — but each quote
        # object carries the correct ISIN-based key back under
        # "instrument_token" (e.g. "NSE_EQ|INE848E01016"), which matches this
        # map's keys exactly. That's what we match on below.
        isin_key_map: dict[str, dict[str, Any]] = {
            i["instrument_key"]: i for i in eq_instruments
        }
        keys = list(isin_key_map.keys())

        batch_size = settings.scanner_batch_size  # 200 keys → URL ≈ 4 KB
        semaphore = asyncio.Semaphore(settings.scanner_concurrency)
        updated = 0
        unmatched = 0

        async def fetch_batch(batch_keys: list[str]) -> None:
            nonlocal updated, unmatched
            for attempt in range(settings.scanner_retries):
                try:
                    async with semaphore:
                        quotes = await self.get_ohlc_quotes(batch_keys)
                    logger.debug(
                        "fetch_prev_close_batch requested=%d received=%d sample_key=%s",
                        len(batch_keys),
                        len(quotes),
                        batch_keys[0] if batch_keys else None,
                    )
                    for raw_key, quote in quotes.items():
                        token = quote.get("instrument_token")
                        instrument = isin_key_map.get(token) if token else None
                        if instrument is None:
                            unmatched += 1
                            continue
                        # During market hours Upstox populates prev_ohlc.close
                        # (yesterday's session close).  Before/after hours it is
                        # absent, but ohlc.close holds the same value — the most
                        # recent completed session's close.  Fall back to it so
                        # the cache is always populated regardless of call time.
                        prev_ohlc = quote.get("prev_ohlc") or {}
                        ohlc = quote.get("ohlc") or {}
                        prev_close = self._to_float(prev_ohlc.get("close")) or self._to_float(ohlc.get("close"))
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

        # Persist — rebuild full list keeping non-EQ instruments unchanged
        eq_set = {i["instrument_key"] for i in eq_instruments}
        non_eq = [i for i in all_instruments if i["instrument_key"] not in eq_set]
        merged = non_eq + eq_instruments
        INSTRUMENT_CACHE.write_text(json.dumps(merged))
        logger.info(
            "fetch_prev_close: updated %d / %d EQ instruments (unmatched=%d)",
            updated,
            len(eq_instruments),
            unmatched,
        )
        return updated

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
        event = raw_event.get("data", raw_event)
        if event.get("update_type") and event.get("update_type") != "order":
            return None
        order_data = event.get("order", event)
        if not isinstance(order_data, dict):
            return None
        raw_token = order_data.get("instrument_token") or order_data.get("instrument_key")
        return OrderEvent(
            order_id=str(order_data.get("order_id") or order_data.get("orderId") or ""),
            status=str(order_data.get("status") or order_data.get("order_status") or "UNKNOWN"),
            transaction_type=order_data.get("transaction_type"),
            tradingsymbol=order_data.get("trading_symbol") or order_data.get("tradingsymbol"),
            instrument_token=raw_token.replace(":", "|") if raw_token else raw_token,
            average_price=self._to_float(order_data.get("average_price") or order_data.get("average_price_value")),
            filled_quantity=self._to_int(order_data.get("filled_quantity")),
            product=order_data.get("product"),
            source=order_data.get("order_ref_id") or order_data.get("source") or order_data.get("placed_by"),
            parent_order_id=order_data.get("parent_order_id"),
            order_type=order_data.get("order_type"),
            status_message=order_data.get("status_message") or order_data.get("message"),
            order_timestamp=(
                order_data.get("order_creation_time")
                or order_data.get("order_timestamp")
                or order_data.get("placed_on")
                or order_data.get("exchange_timestamp")
            ),
            raw=raw_event,
        )

    def normalize_order_book_event(self, payload: dict[str, Any]) -> OrderEvent:
        raw_token = payload.get("instrument_token") or payload.get("instrument_key")
        return OrderEvent(
            order_id=str(payload.get("order_id") or payload.get("order_ref_id") or ""),
            status=str(payload.get("status") or payload.get("order_status") or "UNKNOWN"),
            transaction_type=payload.get("transaction_type"),
            tradingsymbol=payload.get("trading_symbol") or payload.get("tradingsymbol"),
            instrument_token=raw_token.replace(":", "|") if raw_token else raw_token,
            average_price=self._to_float(payload.get("average_price")),
            filled_quantity=self._to_int(payload.get("filled_quantity")),
            product=payload.get("product"),
            source=payload.get("source") or payload.get("order_ref_id") or payload.get("placed_by"),
            parent_order_id=payload.get("parent_order_id"),
            order_type=payload.get("order_type"),
            status_message=payload.get("status_message") or payload.get("message"),
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


upstox_client = UpstoxClient()