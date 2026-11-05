#!/usr/bin/env python3
"""Create public market headlines JSON from publisher-provided RSS metadata."""
import datetime as dt
import email.utils
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "news-feed.json")
SOURCES = [
    ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("CNBC", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/marketpulse/"),
    ("Investing.com", "https://www.investing.com/rss/news_25.rss"),
]
NS = {
    "media": "http://search.yahoo.com/mrss/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
KEYWORDS = re.compile(r"\b(stock|market|wall street|nasdaq|dow|s&p|fed|federal reserve|inflation|interest rate|economy|economic|tariff|trade|earnings|chip|semiconductor|nvidia|apple|microsoft|google|amazon|tesla|ai|artificial intelligence|dollar|currency|treasury|bond|oil|technology|tech|jobs|invest|finance|bank)\b", re.I)
BREAKING = re.compile(r"\b(fed|federal reserve|inflation|earnings|nasdaq|s&p 500|wall street|nvidia|artificial intelligence|tariff|interest rate)\b", re.I)
def txt(el, path):
    v = el.find(path)
    return "".join(v.itertext()).strip() if v is not None else ""
def image_of(item):
    # Only link an image explicitly supplied with the publisher's syndication metadata.
    for tag in ("media:content", "media:thumbnail", "enclosure"):
        for el in item.findall(tag, NS):
            url = el.get("url", "")
            typ = el.get("type", "")
            if url.startswith("https://") and (tag != "enclosure" or typ.startswith("image/")):
                return url
    return None
def parse_date(value):
    try:
        d = email.utils.parsedate_to_datetime(value)
        return d.astimezone(dt.timezone.utc) if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None
now = dt.datetime.now(dt.timezone.utc)
articles = []
seen = set()
for publisher, url in SOURCES:
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"MYM-LTD-Site-NewsFeed/1.0 (+https://mym-ltd.com)","Accept":"application/rss+xml, application/xml, text/xml, */*"})
        with urllib.request.urlopen(req, timeout=18) as res:
            payload = res.read(1_500_000)
        root = ET.fromstring(payload)
        count = 0
        for item in root.findall(".//item")[:70]:
            title = unescape(re.sub(r"<[^>]+>", "", txt(item, "title"))).strip()
            link = txt(item, "link").strip()
            if not title or not link.startswith("https://") or len(title) < 20:
                continue
            if not KEYWORDS.search(title):
                continue
            published = parse_date(txt(item, "pubDate") or txt(item, "dc:date"))
            if published is None or published > now + dt.timedelta(hours=2) or now - published > dt.timedelta(hours=72):
                continue
            fingerprint = re.sub(r"[^a-z0-9]", "", title.lower())[:95]
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            age_hours = max(0, (now - published).total_seconds()/3600)
            priority = 3 if BREAKING.search(title) else 1
            score = priority * 10 + max(0, 48 - age_hours) / 8
            articles.append({"title":title[:220], "url":link, "source":publisher, "published_at":published.isoformat().replace("+00:00","Z"), "image":image_of(item), "score":round(score,2)})
            count += 1
        print(publisher, count, "accepted")
    except Exception as exc:
        print(publisher, "failed:", str(exc)[:240])
articles.sort(key=lambda x:x["score"], reverse=True)
articles = articles[:36]
if len(articles) < 3:
    print("Too few fresh articles; retain existing feed without overwriting")
    raise SystemExit(0)
data = {"updated_at_utc":now.isoformat().replace("+00:00","Z"), "selection":"Editorial relevance and recency; not publisher view counts.", "articles":articles}
with open(OUT,"w",encoding="utf-8") as f:
    json.dump(data,f,ensure_ascii=False,indent=2)
    f.write("\n")
print("Saved", len(articles), "articles; feed image count:", sum(bool(x["image"]) for x in articles))
