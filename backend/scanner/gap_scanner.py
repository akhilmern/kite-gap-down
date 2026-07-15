from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import httpx

from config.settings import IST, settings
from models.schemas import GapCandidate, ScannerRequest
from models.state import state_manager
from utils.kite_client import kite_client

logger = logging.getLogger(__name__)


class GapScanner:
    async def refresh_universe(self) -> int:
        instruments = await kite_client.load_instruments(force_refresh=True)
        return len(instruments)

    async def run(self, request: ScannerRequest | None = None) -> list[GapCandidate]:
        runtime = await state_manager.get_runtime_settings()

        if not state_manager.access_token:
            raise RuntimeError("Cannot run scanner: no Kite access token. Please authenticate first.")

        candidates, instrument_map = await self._run_kite_scan()
        candidates = self._enrich_volume_stats(candidates, instrument_map)

        filtered = self._apply_filters(candidates, request, runtime)
        await state_manager.set_scan_results(filtered)
        results, _ = await state_manager.get_scan_results()
        return results

    async def _run_kite_scan(self) -> tuple[list[GapCandidate], dict[str, Any]]:
        try:
            all_instruments = await kite_client.load_instruments(force_refresh=False)

            # Only EQ instruments with a pre-fetched prev_close
            instruments = [
                item for item in all_instruments
                if item.get("instrument_type") == "EQ"
                and item.get("tradingsymbol")
                and item.get("prev_close")          # must have been pre-fetched
            ]
            no_prev = sum(
                1 for i in all_instruments
                if i.get("instrument_type") == "EQ" and not i.get("prev_close")
            )
            if no_prev:
                logger.warning(
                    "scanner: %d EQ instruments skipped — no prev_close in cache. "
                    "Click 'Fetch prev close' before running the scan.",
                    no_prev,
                )
            logger.info(
                "scanner: %d EQ instruments with prev_close (skipped %d without)",
                len(instruments), no_prev,
            )
            if not instruments:
                return [], {}

            # Kite instrument key format: "NSE:SYMBOL"
            instrument_map = {f"NSE:{item['tradingsymbol']}": item for item in instruments}
            instrument_keys = list(instrument_map.keys())

            batch_size = settings.scanner_batch_size  # 500 keys max per Kite OHLC call
            batches = [
                instrument_keys[i: i + batch_size]
                for i in range(0, len(instrument_keys), batch_size)
            ]
            logger.info(
                "scanner: %d keys → %d batches of ≤%d",
                len(instrument_keys), len(batches), batch_size,
            )

            semaphore = asyncio.Semaphore(settings.scanner_concurrency)

            async def fetch_batch(batch_index: int, keys: list[str]) -> list[GapCandidate]:
                for attempt in range(settings.scanner_retries):
                    try:
                        async with semaphore:
                            quotes = await kite_client.get_ohlc_quotes(keys)
                        candidates = self._build_candidates_from_quotes(quotes, instrument_map)
                        logger.info(
                            "scanner_batch %d/%d: %d quotes → %d candidates",
                            batch_index + 1, len(batches), len(quotes), len(candidates),
                        )
                        return candidates
                    except httpx.HTTPError as exc:
                        if attempt == settings.scanner_retries - 1:
                            logger.error(
                                "scanner_batch_failed batch=%d/%d size=%d error=%s",
                                batch_index + 1, len(batches), len(keys), exc,
                            )
                            return []
                        await asyncio.sleep(2 ** attempt)
                return []

            results = await asyncio.gather(
                *(fetch_batch(i, batch) for i, batch in enumerate(batches))
            )
            flattened = [item for batch in results for item in batch]
            if flattened:
                logger.info("scanner: fetched %d raw candidates", len(flattened))
                return flattened, instrument_map

            logger.warning(
                "scanner: zero candidates. Possible causes: market not open, "
                "token expired, or all stocks have no today open price yet."
            )
            return [], instrument_map
        except Exception:  # noqa: BLE001
            logger.exception("scanner_failed")
            return [], {}

    def _build_candidates_from_quotes(
        self,
        quotes: dict[str, Any],
        instrument_map: dict[str, dict[str, Any]],
    ) -> list[GapCandidate]:
        """
        Build GapCandidate objects from Kite OHLC quotes dict.

        Kite OHLC response is keyed by 'NSE:SYMBOL'.
        Each quote: {instrument_token, timestamp, last_price, ohlc: {open, high, low, close},
                     net_change, oi, ...}

        prev_close is read from the instrument cache (pre-fetched and stored by
        fetch_and_store_prev_close). The ohlc.open is today's open price.
        """
        candidates: list[GapCandidate] = []
        _logged_sample = False

        no_instrument = 0
        no_open = 0

        for instrument_key, quote in quotes.items():
            if not _logged_sample:
                logger.info(
                    "scanner_quote_sample key=%s ohlc=%s",
                    instrument_key, quote.get("ohlc"),
                )
                _logged_sample = True

            instrument = instrument_map.get(instrument_key) or {}
            if not instrument:
                no_instrument += 1
                continue

            # prev_close comes from the pre-fetched cache
            prev_close = self._to_float(instrument.get("prev_close"))
            if prev_close is None or prev_close <= 0:
                continue

            ohlc = quote.get("ohlc") or {}
            open_price = self._to_float(ohlc.get("open"))
            if open_price is None or open_price <= 0:
                no_open += 1
                continue

            ltp = self._to_float(quote.get("last_price")) or self._to_float(ohlc.get("close")) or open_price
            volume = int(self._to_float(quote.get("volume") or 0) or 0)

            gap_pct = ((open_price - prev_close) / prev_close) * 100
            candidates.append(
                GapCandidate(
                    tradingsymbol=instrument.get("tradingsymbol") or instrument_key,
                    exchange=str(instrument.get("exchange") or "NSE"),
                    instrument_token=instrument_key,   # "NSE:SYMBOL"
                    prev_close=round(prev_close, 2),
                    open_price=round(open_price, 2),
                    ltp=round(ltp, 2),
                    gap_pct=round(gap_pct, 2),
                    volume=volume,
                    avg_volume_30d=None,
                    market_cap=None,
                    sector=instrument.get("sector"),
                    scanned_at=datetime.now(IST).isoformat(),
                )
            )

        if no_instrument or no_open:
            logger.info(
                "scanner_build: %d quotes → %d candidates "
                "(skipped: no_instrument=%d, no_open=%d)",
                len(quotes), len(candidates), no_instrument, no_open,
            )
        return candidates

    def _enrich_volume_stats(self, candidates: list[GapCandidate], instrument_map: dict[str, Any]) -> list[GapCandidate]:
        """
        Compute avg_volume_20d and volume_spike for each candidate using the
        pre-fetched ``vol_history`` stored in the instrument cache.
        """
        if not candidates:
            return candidates

        now_ist = datetime.now(IST)
        market_open = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        minutes_elapsed = max(1, (now_ist - market_open).total_seconds() / 60)

        enriched: list[GapCandidate] = []
        cache_hits = 0
        for candidate in candidates:
            instrument = instrument_map.get(candidate.instrument_token) or {}
            vol_history: list[int] = instrument.get("vol_history") or []
            if not vol_history:
                enriched.append(candidate)
                continue
            avg_vol = int(sum(vol_history) / len(vol_history))
            spike: float | None = None
            if avg_vol > 0:
                today_rate = candidate.volume / minutes_elapsed
                avg_rate = avg_vol / 375
                spike = round(today_rate / avg_rate, 2)
            enriched.append(candidate.model_copy(update={"avg_volume_20d": avg_vol, "volume_spike": spike}))
            cache_hits += 1

        logger.info(
            "scanner_enrich: %d/%d candidates enriched with cached 20d volume stats",
            cache_hits, len(candidates),
        )
        return enriched

    def _apply_filters(
        self,
        candidates: list[GapCandidate],
        request: ScannerRequest | None,
        runtime: Any,
    ) -> list[GapCandidate]:
        min_gap = (
            request.min_gap_down_pct
            if request and request.min_gap_down_pct is not None
            else runtime.min_gap_down_pct
        )
        max_gap = (
            request.max_gap_down_pct
            if request and request.max_gap_down_pct is not None
            else runtime.max_gap_down_pct
        )
        min_price = (
            request.min_price if request and request.min_price is not None else runtime.min_price
        )
        min_volume = (
            request.min_volume if request and request.min_volume is not None else runtime.min_volume
        )
        min_avg_volume = (
            request.min_avg_volume_30d
            if request and request.min_avg_volume_30d is not None
            else runtime.min_avg_volume_30d
        )
        min_market_cap = (
            request.min_market_cap
            if request and request.min_market_cap is not None
            else runtime.min_market_cap
        )
        excluded_sectors = set(
            request.excluded_sectors
            if request and request.excluded_sectors is not None
            else runtime.excluded_sectors
        )

        filtered = [
            item
            for item in candidates
            if item.gap_pct <= min_gap
            and item.gap_pct >= max_gap
            and item.ltp >= min_price
            and (item.volume == 0 or item.volume >= min_volume)
            and (item.avg_volume_30d is None or item.avg_volume_30d >= min_avg_volume)
            and (item.market_cap is None or item.market_cap >= min_market_cap)
            and (not item.sector or item.sector not in excluded_sectors)
        ]
        filtered.sort(key=lambda row: row.gap_pct)
        if not filtered and candidates:
            logger.warning(
                "scanner_filter: ALL %d candidates were filtered out "
                "(min_gap=%.1f max_gap=%.1f min_price=%.0f min_vol=%d). "
                "Sample gaps: %s",
                len(candidates),
                min_gap, max_gap, min_price, min_volume,
                [round(c.gap_pct, 2) for c in candidates[:10]],
            )
        else:
            logger.info(
                "scanner_filter: %d candidates -> %d after filter "
                "(min_gap=%.1f max_gap=%.1f min_price=%.0f min_vol=%d)",
                len(candidates), len(filtered), min_gap, max_gap, min_price, min_volume,
            )
        return filtered

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


gap_scanner = GapScanner()
