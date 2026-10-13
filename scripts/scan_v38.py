#!/usr/bin/env python3
"""MYM V38 research-only scanner. No broker orders, Telegram, or portfolio changes."""
import datetime as dt
import json
import pathlib
import sys
import time

import pandas as pd
import requests
import yfinance as yf

ROOT = pathlib.Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc

def universe():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    response = requests.get(url, headers={"User-Agent": "MYM-LTD-Research/1.0 (market research)"}, timeout=25)
    response.raise_for_status()
    table = pd.read_html(response.text)[0]
    return {str(r["Symbol"]).replace(".", "-"): str(r["Security"]) for _, r in table.iterrows()}

def frame(raw, symbol):
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            data = raw[symbol] if symbol in raw.columns.get_level_values(0) else raw.xs(symbol, axis=1, level=1)
        else:
            data = raw
        return data[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except (KeyError, ValueError):
        return pd.DataFrame()

def analyze(symbol, name, df, as_of):
    if len(df) < 210 or str(df.index[-1].date()) != as_of:
        return None
    close, volume = df["Close"], df["Volume"]
    price = float(close.iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    if not (price > ma200 > 0):
        return None
    avg_volume = float(volume.iloc[-21:-1].mean())
    if avg_volume <= 0:
        return None
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    down_last = float(down.iloc[-1])
    rsi = 100.0 if down_last == 0 else 100 - 100 / (1 + float(up.iloc[-1]) / down_last)
    lower = float(close.rolling(20).mean().iloc[-1] - 2 * close.rolling(20).std().iloc[-1])
    score, reasons = 20, ["Above SMA200"]
    if price <= lower:
        score += 10
        reasons.append("Bollinger lower band")
    if rsi <= 35:
        score += 30
        reasons.append("RSI <= 35")
    elif rsi <= 45:
        score += 10
        reasons.append("RSI <= 45")
    volume_ratio = float(volume.iloc[-1]) / avg_volume
    if price > float(df["Open"].iloc[-1]) and volume_ratio > 1.5:
        score += 15
        reasons.append("Bullish candle + volume > 1.5x")
    if score < 50:
        return None
    prev = close.shift()
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev).abs(), (df["Low"] - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1/14, adjust=False).mean().iloc[-1])
    if atr <= 0:
        return None
    return {"symbol": symbol, "name": name, "score": score, "close": round(price, 2),
            "rsi": round(rsi, 1), "volume_ratio": round(volume_ratio, 2),
            "atr_stop": round(price - 2 * atr, 2), "reasons": reasons}

def main():
    report = json.loads((ROOT / "report.json").read_text(encoding="utf-8"))
    as_of = report["as_of"]
    names = universe()
    spy = yf.download("SPY", period="2y", auto_adjust=True, progress=False, threads=False)
    spy = frame(spy, "SPY")
    if len(spy) < 200 or str(spy.index[-1].date()) != as_of:
        raise RuntimeError("SPY date does not match daily market report; no file changed")
    risk_on = float(spy["Close"].iloc[-1]) > float(spy["Close"].rolling(200).mean().iloc[-1])
    candidates, checked, errors = [], 0, 0
    symbols = sorted(names)
    if risk_on:
        for start in range(0, len(symbols), 40):
            batch = symbols[start:start+40]
            try:
                raw = yf.download(batch, period="2y", group_by="ticker", auto_adjust=True,
                                  progress=False, threads=True, timeout=40)
            except Exception as exc:
                print("Batch error:", exc, file=sys.stderr)
                errors += len(batch)
                continue
            for symbol in batch:
                df = frame(raw, symbol)
                if len(df) < 210 or str(df.index[-1].date()) != as_of:
                    errors += 1
                    continue
                checked += 1
                item = analyze(symbol, names[symbol], df, as_of)
                if item:
                    candidates.append(item)
            time.sleep(1)
    candidates.sort(key=lambda item: (-item["score"], item["rsi"], item["symbol"]))
    if risk_on and checked < int(len(symbols) * .8):
        raise RuntimeError(f"Insufficient coverage: {checked}/{len(symbols)}; previous output preserved")
    payload = {"status": "ok", "as_of": as_of, "updated_at_utc": dt.datetime.now(UTC).isoformat(timespec="minutes"),
               "market_gate": "open" if risk_on else "blocked_spy_below_sma200",
               "universe_count": len(symbols), "checked_count": checked, "data_errors": errors,
               "method": "V37 technical screen only; no news or portfolio execution; research, not trade advice",
               "candidates": candidates[:20]}
    dest = ROOT / "watchlist.json"
    temp = dest.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(dest)
    print("V38 WATCHLIST", as_of, "checked", checked, "candidates", len(candidates), "market", payload["market_gate"])

if __name__ == "__main__":
    main()
