#!/usr/bin/env python3
"""Update MYM report using Stooq daily ETF CSV; stdlib only. Never fabricate missing data."""
import csv,io,json,re,time,urllib.request,datetime,statistics,pathlib,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
MAIN={'SPY':'S&P 500 ETF','QQQ':'Nasdaq 100 ETF','DIA':'Dow ETF','IWM':'Russell 2000 ETF'}
SECTORS={'XLK':'Technology','XLF':'Financials','XLV':'Health Care','XLE':'Energy','XLI':'Industrials','XLY':'Consumer Discretionary','XLP':'Consumer Staples','XLU':'Utilities','XLB':'Materials','XLRE':'Real Estate','XLC':'Communication Services'}
def fetch(sym):
    url='https://stooq.com/q/d/l/?s='+sym.lower()+'.us&i=d'
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; MYM-Research/1.0)'})
    with urllib.request.urlopen(req,timeout=22) as response: content=response.read(6000000).decode('utf-8-sig')
    rows=list(csv.DictReader(io.StringIO(content)))
    vals=[]
    for row in rows:
        try:
            day=datetime.date.fromisoformat(row['Date']);close=float(row['Close'])
            if close>0: vals.append((day,close))
        except (ValueError,KeyError,TypeError):pass
    vals.sort()
    if len(vals)<51:raise ValueError(sym+': insufficient history')
    if (datetime.datetime.now(datetime.timezone.utc).date()-vals[-1][0]).days>7:raise ValueError(sym+': stale prices')
    return vals

def build():
    series={}
    for sym in list(MAIN)+list(SECTORS):
        try:series[sym]=fetch(sym)
        except Exception as e:print('SKIP',sym,str(e),file=sys.stderr)
        time.sleep(.15)
    if any(s not in series for s in MAIN):raise RuntimeError('Missing required major ETFs; previous report preserved')
    dates=[series[s][-1][0] for s in MAIN]
    if len(set(dates))!=1:raise RuntimeError('Major ETFs have inconsistent close dates')
    asof=dates[0]
    def record(sym,name):
        vals=[v for d,v in series[sym] if d<=asof]
        days=[d for d,v in series[sym] if d<=asof]
        if len(vals)<51 or days[-1]!=asof:return None
        return {'symbol':sym,'name':name,'close':round(vals[-1],2),'change_pct':round((vals[-1]/vals[-2]-1)*100,2),'above_ma20':vals[-1]>statistics.mean(vals[-20:]),'above_ma50':vals[-1]>statistics.mean(vals[-50:])}
    main=[record(s,n) for s,n in MAIN.items()]
    if any(x is None for x in main):raise RuntimeError('Incomplete major ETF records')
    sectors=[x for s,n in SECTORS.items() if (x:=record(s,n)) is not None]
    sectors.sort(key=lambda x:x['change_pct'],reverse=True)
    return {'status':'ok','updated_at_utc':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M'),'as_of':asof.isoformat(),'instruments':main,'sectors':sectors,'trend_count':sum(x['above_ma20'] for x in main),'breadth':sum(x['change_pct']>0 for x in sectors),'source':'Stooq daily ETF price CSV','method':'Daily return, SMA20, SMA50; ETF proxies'}
def main():
    data=build()
    report=ROOT/'report.json'; html=ROOT/'index.html'
    source=html.read_text(encoding='utf-8')
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')
    pattern=r'(<script id="mym-report-data" type="application/json">).*?(</script>)'
    changed,n=re.subn(pattern,lambda m:m.group(1)+payload+m.group(2),source,count=1,flags=re.S)
    if n!=1:raise RuntimeError('Embedded report slot not found')
    html.write_text(changed,encoding='utf-8')
    report.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Updated',data['as_of'],len(data['sectors']),'sectors')
if __name__=='__main__':main()
