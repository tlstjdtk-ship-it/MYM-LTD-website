
#!/usr/bin/env python3
"""MYM daily ETF market report. No fabricated market data."""

import datetime
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]

MAIN = {
    "SPY": "S&P 500 ETF",
    "QQQ": "Nasdaq 100 ETF",
    "DIA": "Dow ETF",
    "IWM": "Russell 2000 ETF",
}

SECTORS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}


def fetch(symbol):
    base = "https://query1.finance.yahoo.com/v8/finance/chart/"
    url = base + urllib.parse.quote(symbol) + "?range=1y&interval=1d"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "MYM-LTD-Market-Research/1.0",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.load(response)

    chart = data.get("chart", {})
    results = chart.get("result")

    if not results:
        raise ValueError(symbol + ": no market data returned")

    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote") or []

    if not quotes:
        raise ValueError(symbol + ": no daily prices")

    closes = quotes[0].get("close") or []
    exchange_timezone = datetime.timezone.utc

    meta = result.get("meta") or {}
    offset = meta.get("gmtoffset", -14400)

    if isinstance(offset, (int, float)):
        exchange_timezone = datetime.timezone(
            datetime.timedelta(seconds=int(offset))
        )

    daily = {}

    for timestamp, close in zip(timestamps, closes):
        if close is None:
            continue

        try:
            price = float(close)
            day = datetime.datetime.fromtimestamp(
                timestamp, exchange_timezone
            ).date()

            if price > 0:
                daily[day] = price
        except (ValueError, TypeError, OverflowError):
            continue

    values = sorted(daily.items())

    if len(values) < 51:
        raise ValueError(symbol + ": insufficient history")

    today = datetime.datetime.now(datetime.timezone.utc).date()
    last_day = values[-1][0]

    if last_day > today:
        raise ValueError(symbol + ": future-dated prices")

    if (today - last_day).days > 7:
        raise ValueError(symbol + ": stale prices")

    print("FETCH OK", symbol, last_day, len(values))
    return values


def build():
    series = {}

    for symbol in list(MAIN) + list(SECTORS):
        try:
            series[symbol] = fetch(symbol)
        except Exception as error:
            print("SKIP", symbol, str(error), file=sys.stderr)

        time.sleep(0.5)

    missing = [symbol for symbol in MAIN if symbol not in series]

    if missing:
        raise RuntimeError(
            "Missing required major ETFs: "
            + ", ".join(missing)
            + "; previous report preserved"
        )

    dates = [series[symbol][-1][0] for symbol in MAIN]

    if len(set(dates)) != 1:
        raise RuntimeError(
            "Major ETFs have inconsistent close dates; "
            "previous report preserved"
        )

    as_of = dates[0]

    def record(symbol, name):
        entries = [
            (day, value)
            for day, value in series[symbol]
            if day <= as_of
        ]

        if len(entries) < 51 or entries[-1][0] != as_of:
            return None

        prices = [value for _, value in entries]

        return {
            "symbol": symbol,
            "name": name,
            "close": round(prices[-1], 2),
            "change_pct": round(
                (prices[-1] / prices[-2] - 1) * 100, 2
            ),
            "above_ma20": (
                prices[-1] > statistics.mean(prices[-20:])
            ),
            "above_ma50": (
                prices[-1] > statistics.mean(prices[-50:])
            ),
        }

    instruments = [
        record(symbol, name)
        for symbol, name in MAIN.items()
    ]

    if any(item is None for item in instruments):
        raise RuntimeError(
            "Incomplete major ETF records; previous report preserved"
        )

    sectors = []

    for symbol, name in SECTORS.items():
        if symbol in series:
            item = record(symbol, name)
            if item is not None:
                sectors.append(item)

    sectors.sort(
        key=lambda item: item["change_pct"],
        reverse=True,
    )

    now = datetime.datetime.now(datetime.timezone.utc)

    return {
        "status": "ok",
        "updated_at_utc": now.strftime("%Y-%m-%d %H:%M"),
        "as_of": as_of.isoformat(),
        "instruments": instruments,
        "sectors": sectors,
        "trend_count": sum(
            item["above_ma20"] for item in instruments
        ),
        "breadth": sum(
            item["change_pct"] > 0 for item in sectors
        ),
        "source": "Yahoo Finance daily ETF chart data",
        "method": "Daily return, SMA20, SMA50; ETF proxies",
    }


def main():
    data = build()

    html_path = ROOT / "index.html"
    report_path = ROOT / "report.json"

    html = html_path.read_text(encoding="utf-8")

    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")

    pattern = (
        r'(<script\s+id=["\']mym-report-data["\']'
        r'\s+type=["\']application/json["\']\s*>)'
        r'.*?(</script\s*>)'
    )

    updated_html, count = re.subn(
        pattern,
        lambda match: match.group(1) + payload + match.group(2),
        html,
        count=1,
        flags=re.S | re.I,
    )

    if count != 1:
        raise RuntimeError(
            "Embedded report slot not found; files unchanged"
        )

    report_text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )

    html_path.write_text(updated_html, encoding="utf-8")
    report_path.write_text(report_text, encoding="utf-8")

    print(
        "REPORT UPDATED:",
        data["as_of"],
        "| Major ETFs:",
        len(data["instruments"]),
        "| Sectors:",
        len(data["sectors"]),
    )


if __name__ == "__main__":
    main()
