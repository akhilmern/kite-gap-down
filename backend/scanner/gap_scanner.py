from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from backend.config.settings import RuntimeSettings, get_settings
from backend.models.schemas import GapCandidate
from backend.utils.kite_client import kite_client

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_MARKET_CAP_MULTIPLIERS = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}


def _parse_market_cap(cap_str: Optional[str]) -> float:
    if not cap_str:
        return 0.0
    cap_str = cap_str.strip().upper()
    for suffix, mult in _MARKET_CAP_MULTIPLIERS.items():
        if cap_str.endswith(suffix):
            try:
                return float(cap_str[:-1]) * mult
            except ValueError:
                return 0.0
    try:
        return float(cap_str)
    except ValueError:
        return 0.0


class GapScanner:
    """Scans NSE EQ instruments for gap-down fill candidates."""

    async def run(self, settings: Optional[RuntimeSettings] = None) -> List[GapCandidate]:
        rs = settings or get_settings()
        cache = kite_client.load_instruments_cache()
        if not cache:
            logger.warning("No instrument cache. Run 'Refresh Universe' first.")
            return []

        symbols = list(cache.keys())
        logger.info("Scanning %d instruments for gap-down…", len(symbols))

        # Batch-fetch OHLC (500 per batch, 3 concurrent)
        batches: List[List[str]] = []
        batch_size = 500
        for i in range(0, len(symbols), batch_size):
            batches.append([f"NSE:{s}" for s in symbols[i : i + batch_size]])

        sem = asyncio.Semaphore(3)
        ohlc_data: Dict[str, Any] = {}

        async def _fetch_batch(batch: List[str]) -> None:
            async with sem:
                try:
                    result = await kite_client.get_ohlc(batch)
                    ohlc_data.update(result)
                except Exception as exc:
                    logger.error("OHLC batch error: %s", exc)

        await asyncio.gather(*[_fetch_batch(b) for b in batches])

        now_ist = datetime.now(IST)
        # Minutes since market open reference (09:00)
        market_open_ref = now_ist.replace(hour=9, minute=0, second=0, microsecond=0)
        mins_elapsed = max(1, (now_ist - market_open_ref).total_seconds() / 60)

        min_cap = _parse_market_cap(rs.min_market_cap)
        excluded_sectors_lower = {s.lower() for s in rs.excluded_sectors}

        candidates: List[GapCandidate] = []

        for sym, info in cache.items():
            key = f"NSE:{sym}"
            ohlc = ohlc_data.get(key, {})
            if not ohlc:
                continue

            ohlc_inner = ohlc.get("ohlc", {})
            open_price = float(ohlc_inner.get("open", 0) or 0)
            ltp = float(ohlc.get("last_price", 0) or 0)

            prev_close = float(info.get("prev_close") or 0)
            if prev_close <= 0 or open_price <= 0:
                continue

            gap_pct = (open_price - prev_close) / prev_close * 100

            # --- Gap filter ---
            if not (rs.max_gap_down_pct <= gap_pct <= rs.min_gap_down_pct):
                continue

            # --- Price filter ---
            if open_price < rs.min_price:
                continue

            # --- Volume ---
            volume = int(ohlc.get("volume", 0) or 0)
            if volume < rs.min_volume:
                continue

            # --- Avg volume 20d ---
            vol_history: List[int] = info.get("vol_history", [])
            avg_vol_20d: Optional[int] = None
            vol_spike: Optional[float] = None
            if vol_history:
                avg_vol_20d = int(sum(vol_history) / len(vol_history))
                if avg_vol_20d < rs.min_avg_volume_30d:
                    continue
                spike_rate = volume / mins_elapsed
                avg_rate = avg_vol_20d / 375
                vol_spike = round(spike_rate / avg_rate, 2) if avg_rate > 0 else None
            elif rs.min_avg_volume_30d > 0:
                # No history → skip if filter demands it
                pass

            # --- Market cap ---
            cap_str: Optional[str] = info.get("market_cap")
            cap_val = _parse_market_cap(cap_str)
            if min_cap > 0 and cap_val > 0 and cap_val < min_cap:
                continue

            # --- Sector exclusion ---
            sector: Optional[str] = info.get("sector")
            if sector and sector.lower() in excluded_sectors_lower:
                continue

            token = int(info.get("instrument_token", 0))
            high = float(ohlc_inner.get("high", 0) or 0)
            low = float(ohlc_inner.get("low", 0) or 0)

            candidate = GapCandidate(
                tradingsymbol=sym,
                exchange="NSE",
                instrument_token=token,
                prev_close=prev_close,
                open_price=open_price,
                ltp=ltp or open_price,
                high=high,
                low=low,
                gap_pct=round(gap_pct, 4),
                volume=volume,
                avg_volume_20d=avg_vol_20d,
                volume_spike=vol_spike,
                market_cap=cap_str,
                sector=sector,
                scanned_at=now_ist.isoformat(),
                buy_limit_price=round(open_price * (1 + get_settings().buy_buffer_pct / 100), 2),
            )
            candidates.append(candidate)

        # Sort by gap % ascending (most gapped down first)
        candidates.sort(key=lambda c: c.gap_pct)
        logger.info("Gap scan found %d candidates", len(candidates))
        return candidates

    async def fetch_preopen_depth(self, candidates: List[GapCandidate]) -> List[GapCandidate]:
        """Enrich candidates with pre-open order book depth."""
        instruments = [f"NSE:{c.tradingsymbol}" for c in candidates]
        try:
            quotes = await kite_client.get_quote(instruments)
        except Exception as exc:
            logger.error("Depth fetch error: %s", exc)
            return candidates

        updated = []
        for c in candidates:
            key = f"NSE:{c.tradingsymbol}"
            q = quotes.get(key, {})
            depth = q.get("depth", {})
            buy_depth = depth.get("buy", [])
            sell_depth = depth.get("sell", [])
            buy_qty = sum(int(d.get("quantity", 0)) for d in buy_depth)
            sell_qty = sum(int(d.get("quantity", 0)) for d in sell_depth)
            total = buy_qty + sell_qty
            c = c.model_copy(update={
                "preopen_buy_qty": buy_qty,
                "preopen_sell_qty": sell_qty,
                "preopen_buy_pct": round(buy_qty / total * 100, 1) if total > 0 else None,
                "preopen_sell_pct": round(sell_qty / total * 100, 1) if total > 0 else None,
                "ltp": float(q.get("last_price", c.ltp) or c.ltp),
            })
            updated.append(c)
        return updated

    async def filter_intraday(self, candidates: List[GapCandidate]) -> List[GapCandidate]:
        """Filter candidates to intraday-eligible only (NSE EQ is always MIS-eligible)."""
        return [c for c in candidates if c.exchange == "NSE"]


gap_scanner = GapScanner()
