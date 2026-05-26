#!/usr/bin/env python3
"""
Congressional Trade Scanner — Munya Mututa Morning Brief
Pulls STOCK Act disclosures for your current holdings via QuiverQuant API.
Run daily via GitHub Actions or manually: python congress_scanner.py

Setup:
  pip install requests python-dotenv
  Set QUIVERQUANT_API_KEY in .env or environment variable.
  Free tier: https://www.quiverquant.com/  (~$10/mo for full access)
  Fallback: FMP API (set FMP_API_KEY) — covers Senate + House separately.
"""

import os
import json
import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────

QUIVER_KEY = os.getenv("QUIVERQUANT_API_KEY")
FMP_KEY    = os.getenv("FMP_API_KEY")

# Your current holdings (auto-synced to E*TRADE CSV — update monthly)
HOLDINGS = [
    "AGX", "AAPL", "AXTI", "CHAT", "CIEN", "CLS", "CLYM", "CSTM",
    "DIA", "EZPW", "GOOG", "KSKGF", "LITE", "MMSMY", "PARR",
    "SNDK", "SOXX", "SSRM", "TTMI", "UNFI", "VIAV",
]

# Watchlist — flag if congress buys these before you do
WATCHLIST = ["MU", "VRT", "KTOS", "WMT", "RSG", "ALAB", "AVAV", "BABA", "EWJ"]

ALL_TICKERS = HOLDINGS + WATCHLIST

LOOKBACK_DAYS = 14   # how far back to scan (STOCK Act allows 45-day lag)

# ── QUIVERQUANT FETCH ─────────────────────────────────────────────────────────

def fetch_quiver(ticker: str) -> list[dict]:
    """Fetch congressional trades for a ticker from QuiverQuant."""
    url = f"https://api.quiverquant.com/beta/historical/congresstrading/{ticker}"
    headers = {"Authorization": f"Token {QUIVER_KEY}"}
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200:
        return r.json()
    return []


def fetch_all_recent_quiver(lookback: int) -> list[dict]:
    """Fetch all recent congressional trades (bulk endpoint, if subscribed)."""
    url = "https://api.quiverquant.com/beta/live/congresstrading"
    headers = {"Authorization": f"Token {QUIVER_KEY}"}
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 200:
        return r.json()
    return []


# ── FMP FALLBACK ──────────────────────────────────────────────────────────────

def fetch_fmp_senate(ticker: str) -> list[dict]:
    url = f"https://financialmodelingprep.com/api/v4/senate-trading?symbol={ticker}&apikey={FMP_KEY}"
    r = requests.get(url, timeout=10)
    return r.json() if r.status_code == 200 else []


def fetch_fmp_house(ticker: str) -> list[dict]:
    url = f"https://financialmodelingprep.com/api/v4/house-disclosure?symbol={ticker}&apikey={FMP_KEY}"
    r = requests.get(url, timeout=10)
    return r.json() if r.status_code == 200 else []


# ── FILTER + FORMAT ───────────────────────────────────────────────────────────

def parse_date(d: str) -> datetime.date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(d, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def filter_recent(trades: list[dict], key: str, days: int) -> list[dict]:
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    out = []
    for t in trades:
        d = parse_date(t.get(key, ""))
        if d and d >= cutoff:
            out.append(t)
    return out


def normalize_quiver(raw: list[dict], ticker: str) -> list[dict]:
    """Normalize QuiverQuant response to standard shape."""
    out = []
    for t in raw:
        out.append({
            "source":    "QuiverQuant",
            "ticker":    ticker,
            "member":    t.get("Representative", t.get("Senator", "Unknown")),
            "chamber":   t.get("Chamber", "?"),
            "tx_date":   t.get("Date", ""),
            "filed_date": t.get("FiledAfterDeadline", t.get("Date", "")),
            "tx_type":   t.get("Transaction", ""),
            "amount":    t.get("Range", t.get("Amount", "")),
            "party":     t.get("Party", ""),
        })
    return out


def normalize_fmp(raw: list[dict], ticker: str, chamber: str) -> list[dict]:
    out = []
    for t in raw:
        out.append({
            "source":    f"FMP ({chamber})",
            "ticker":    ticker,
            "member":    t.get("senator", t.get("representative", "Unknown")),
            "chamber":   chamber,
            "tx_date":   t.get("transactionDate", t.get("date", "")),
            "filed_date": t.get("disclosureDate", ""),
            "tx_type":   t.get("type", t.get("transactionType", "")),
            "amount":    t.get("amount", ""),
            "party":     t.get("party", ""),
        })
    return out


# ── MAIN SCAN ─────────────────────────────────────────────────────────────────

def scan() -> list[dict]:
    results = []
    source = "quiver" if QUIVER_KEY else ("fmp" if FMP_KEY else None)

    if source is None:
        print("❌  No API key found. Set QUIVERQUANT_API_KEY or FMP_API_KEY in .env")
        return []

    print(f"🔍  Scanning {len(ALL_TICKERS)} tickers (last {LOOKBACK_DAYS}d) via {source.upper()}...\n")

    for ticker in ALL_TICKERS:
        try:
            if source == "quiver":
                raw = fetch_quiver(ticker)
                normalized = normalize_quiver(raw, ticker)
                recent = filter_recent(normalized, "tx_date", LOOKBACK_DAYS)
            else:
                senate = normalize_fmp(fetch_fmp_senate(ticker), ticker, "Senate")
                house  = normalize_fmp(fetch_fmp_house(ticker),  ticker, "House")
                recent = (filter_recent(senate, "tx_date", LOOKBACK_DAYS) +
                          filter_recent(house,  "tx_date", LOOKBACK_DAYS))

            results.extend(recent)

        except Exception as e:
            print(f"  ⚠️  {ticker}: {e}")

    return results


# ── PRINT BRIEF ───────────────────────────────────────────────────────────────

PARTY_EMOJI = {"D": "🔵", "R": "🔴", "I": "⚪"}
TX_EMOJI    = {"Purchase": "🟢 BUY", "Sale": "🔴 SELL", "Sale (Full)": "🔴 SELL (Full)",
               "Sale (Partial)": "🟡 SELL (Partial)", "Exchange": "🔄 EXCHANGE"}

def print_brief(trades: list[dict]):
    today = datetime.date.today().strftime("%A %b %d, %Y")
    print("=" * 62)
    print(f"  CONGRESSIONAL TRADE SCANNER — {today}")
    print("=" * 62)

    if not trades:
        print(f"\n  ✅  No congressional trades in your holdings/watchlist")
        print(f"      in the last {LOOKBACK_DAYS} days.\n")
        return

    # Split holdings vs watchlist hits
    holding_hits  = [t for t in trades if t["ticker"] in HOLDINGS]
    watchlist_hits = [t for t in trades if t["ticker"] in WATCHLIST]

    def print_section(items: list[dict], label: str):
        if not items:
            return
        # Group by ticker
        by_ticker: dict[str, list] = {}
        for t in items:
            by_ticker.setdefault(t["ticker"], []).append(t)

        print(f"\n  {'━'*55}")
        print(f"  {label} ({len(by_ticker)} tickers, {len(items)} trades)")
        print(f"  {'━'*55}")

        for ticker, txs in sorted(by_ticker.items()):
            tag = "📌 HOLDING" if ticker in HOLDINGS else "👁 WATCHLIST"
            print(f"\n  {ticker}  {tag}")
            for t in sorted(txs, key=lambda x: x["tx_date"], reverse=True):
                party  = PARTY_EMOJI.get(t["party"], "⚪")
                action = TX_EMOJI.get(t["tx_type"], t["tx_type"])
                print(f"    {party} {t['member']:<30} {action}")
                print(f"       Amount: {t['amount']}   Date: {t['tx_date']}   Filed: {t['filed_date']}")

    print_section(holding_hits,  "⚠️  YOUR HOLDINGS — Congress Activity")
    print_section(watchlist_hits, "📡  WATCHLIST — Congress Activity")

    # Quick summary line for morning brief copy-paste
    print(f"\n  {'─'*55}")
    buy_count  = sum(1 for t in trades if "Purchase" in t.get("tx_type", ""))
    sell_count = sum(1 for t in trades if "Sale"     in t.get("tx_type", ""))
    print(f"  SUMMARY: {len(trades)} trade(s) — {buy_count} buy(s), {sell_count} sell(s)")
    print(f"  {'─'*55}\n")


# ── OPTIONAL: SAVE JSON ───────────────────────────────────────────────────────

def save_json(trades: list[dict], path: str = "congress_trades.json"):
    with open(path, "w") as f:
        json.dump({"generated": str(datetime.date.today()), "trades": trades}, f, indent=2)
    print(f"  💾  Saved to {path}")


# ── ENTRY ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    trades = scan()
    print_brief(trades)
    if trades:
        save_json(trades)
