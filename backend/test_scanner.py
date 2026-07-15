#!/usr/bin/env python3
"""
Diagnostic test script for Kite Connect API.
Run this during market hours (9:15-15:30 IST) with a valid access token.
It calls the OHLC and full quote endpoints with 5 known NSE EQ stocks.

Usage: python3 test_scanner.py <access_token>
   OR: set KITE_ACCESS_TOKEN and KITE_API_KEY in .env
"""
import asyncio, sys, json
import httpx
from pathlib import Path

API_KEY = ""
TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""

# Try to read from .env
for line in Path("../.env").read_text().splitlines():
    if line.startswith("KITE_ACCESS_TOKEN="):
        TOKEN = TOKEN or line.split("=", 1)[1].strip()
    if line.startswith("KITE_API_KEY="):
        API_KEY = line.split("=", 1)[1].strip()

if not TOKEN or not API_KEY:
    print("Usage: python3 test_scanner.py <access_token>  OR set KITE_ACCESS_TOKEN+KITE_API_KEY in .env")
    sys.exit(1)

# 5 well-known NSE EQ stocks (Kite format: EXCHANGE:SYMBOL)
KEYS = [
    "NSE:RELIANCE",
    "NSE:WIPRO",
    "NSE:INFY",
    "NSE:HDFCBANK",
    "NSE:MARUTI",
]

KITE_API_BASE = "https://api.kite.trade"


async def main():
    async with httpx.AsyncClient(timeout=15) as client:
        hdrs = {
            "X-Kite-Version": "3",
            "Authorization": f"token {API_KEY}:{TOKEN}",
        }

        print("=== Testing /quote/ohlc ===")
        r = await client.get(
            f"{KITE_API_BASE}/quote/ohlc",
            params={"i": KEYS},
            headers=hdrs,
        )
        print(f"Status: {r.status_code}")
        data = r.json().get("data", {})
        for k, v in data.items():
            print(f"  {k}:")
            print(f"    fields present: {list(v.keys())}")
            print(f"    ohlc: {v.get('ohlc')}")        # {open, high, low, close=prev_close}
            print(f"    last_price: {v.get('last_price')}")

        print()
        print("=== Testing /quote (full quotes) ===")
        r2 = await client.get(
            f"{KITE_API_BASE}/quote",
            params={"i": KEYS},
            headers=hdrs,
        )
        print(f"Status: {r2.status_code}")
        data2 = r2.json().get("data", {})
        for k, v in data2.items():
            print(f"  {k}:")
            print(f"    fields present: {list(v.keys())}")
            print(f"    ohlc: {v.get('ohlc')}")
            print(f"    last_price: {v.get('last_price')}")
            print(f"    volume: {v.get('volume')}")
            depth = v.get("depth") or {}
            print(f"    depth.buy[0]: {(depth.get('buy') or [{}])[0]}")
            print(f"    depth.sell[0]: {(depth.get('sell') or [{}])[0]}")


asyncio.run(main())
