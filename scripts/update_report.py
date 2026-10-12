#!/usr/bin/env python3
"""Update MYM report from Stooq daily ETF CSV. Standard library only."""
import csv
import datetime
import io
import json
import pathlib
import re
import statistics
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]

MAIN = {
    'SPY': 'S&P 500 ETF',
    'QQQ': 'Nasdaq 100 ETF',
    'DIA': 'Dow ETF',
    'IWM': 'Russell 2000 ETF',
}

SECTORS = {
    'XLK': 'Technology',
    'XLF': 'Financials',
    'XLV': 'Health Care',
    'XLE': 'Energy',
    'XLI': 'Industrials',
    'XLY': 'Consumer Discretionary',
    'XLP': 'Consumer Staples',
    'XLU': 'Utilities',
    'XLB': 'Materials',
    'XLRE': 'Real Estate',
    'XLC': 'Communication Services',
}


def fetch(symbol):
    url = 'https://stooq.com/q/d/l/?s=' + symbol.lower() + '.us&i=d'
    request = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0 MYM-Research/1.0'}
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        content = response.read(6000000).decode('utf-8-sig')

    rows = list(csv.DictReader(io.StringIO(content)))

    if len(rows) < 51:
        print(
            'DATA DEBUG',
            symbol,
            'rows=', len(rows),
            'response=', repr(content[:250]),
            file=sys.stderr
        )
        raise ValueError(symbol + ': insufficient CSV rows')

    values = []

    for row in rows:
        try:
            day = datetime.date.fromisoformat(row['Date'])
            close = float(row['Close'])

            if close > 0:
                values.append((day, close))

        except (ValueError, KeyError, TypeError):
            continue

    values.sort(key=lambda item: item[0])

    if len(values) < 51:
        raise ValueError(symbol + ': insufficient valid history')

    today = datetime.datetime.now(datetime.timezone.utc).date()

    if (today - values[-1][0]).days > 7:
        raise ValueError(symbol + ': stale prices')

    if values[-1][0] > today:
        raise ValueError(symbol + ': future-dated prices')

    return values


def build():
    series = {}

    for symbol in list(MAIN) + list(SECTORS):
        try:
            series[symbol] = fetch(symbol)

        except Exception as error:
            print('SKIP', symbol, str(error), file=sys.stderr)

        time.sleep(0.15)

    missing = [
        symbol for symbol in MAIN
        if symbol not in series
    ]

    if missing:
        raise RuntimeError(
            'Missing required major ETFs: '
            + ', '.join(missing)
            + '; previous report preserved'
        )

    dates = [
        series[symbol][-1][0]
        for symbol in MAIN
    ]

    if len(set(dates)) != 1:
        raise RuntimeError(
            'Major ETFs have inconsistent close dates'
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
            'symbol': symbol,
            'name': name,
            'close': round(prices[-1], 2),
            'change_pct': round(
                (prices[-1] / prices[-2] - 1) * 100,
                2
            ),
            'above_ma20': (
                prices[-1] > statistics.mean(prices[-20:])
            ),
            'above_ma50': (
                prices[-1] > statistics.mean(prices[-50:])
            ),
        }

    instruments = [
        record(symbol, name)
        for symbol, name in MAIN.items()
    ]

    if any(item is None for item in instruments):
        raise RuntimeError(
            'Incomplete major ETF records; previous report preserved'
        )

    sectors = []

    for symbol, name in SECTORS.items():
        if symbol in series:
            item = record(symbol, name)

            if item is not None:
                sectors.append(item)

    sectors.sort(
        key=lambda item: item['change_pct'],
        reverse=True
    )

    return {
        'status': 'ok',
        'updated_at_utc': (
            datetime.datetime.now(datetime.timezone.utc)
            .strftime('%Y-%m-%d %H:%M')
        ),
        'as_of': as_of.isoformat(),
        'instruments': instruments,
        'sectors': sectors,
        'trend_count': sum(
            item['above_ma20'] for item in instruments
        ),
        'breadth': sum(
            item['change_pct'] > 0 for item in sectors
        ),
        'source': 'Stooq daily ETF price CSV',
        'method': 'Daily return, SMA20, SMA50; ETF proxies',
    }


def main():
    data = build()

    report_path = ROOT / 'report.json'
    html_path = ROOT / 'index.html'

    html = html_path.read_text(encoding='utf-8')

    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(',', ':')
    )

    payload = payload.replace('<', '\\u003c')

    pattern = (
        r'(<script id="mym-report-data" '
        r'type="application/json">).*?(</script>)'
    )

    updated_html, count = re.subn(
        pattern,
        lambda match: (
            match.group(1) + payload + match.group(2)
        ),
        html,
        count=1,
        flags=re.S,
    )

    if count != 1:
        raise RuntimeError(
            'Embedded report slot not found; files unchanged'
        )

    html_path.write_text(
        updated_html,
        encoding='utf-8'
    )

    report_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding='utf-8'
    )

    print(
        'Updated',
        data['as_of'],
        len(data['sectors']),
        'sectors'
    )


if __name__ == '__main__':
    main()
