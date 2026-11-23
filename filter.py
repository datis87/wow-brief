import json, os, re, urllib.request, datetime as dt
import xml.etree.ElementTree as ET

FEEDS = [
 "https://www.warcrafttavern.com/forever/news/feed/",
 "https://blizzardwatch.com/category/warcraft/wow-forever/feed/",
 "https://massivelyop.com/feed/",
 "https://www.wowhead.com/news/rss/all",
]
MODEL = "gemini-flash-latest"
KEY = os.environ["GEMINI_API_KEY"]
TOPIC = os.environ["NTFY_TOPIC"]
UA = {"User-Agent": "Mozilla/5.0 wow-brief"}
TITLES = {"class_changes": "Class changes", "rankings_sims": "Rankings and sims",
          "auction_house": "Auction House", "strategy": "Gold strategy", "game_news": "Game news"}
PROMPT = """You filter World of Warcraft: Forever news for a busy player.
Use ONLY the items below. Keep items with real substance: hotfix/patch notes, class or spec changes,
balance or tier analysis, sim data, Auction House/economy changes, gold strategies, major announcements.
Drop clickbait, rumors, promos, boosting or gold-selling ads, duplicates, and anything not about WoW Forever.
Merge duplicate coverage into one entry. Return JSON exactly like:
{"class_changes":[],"rankings_sims":[],"auction_house":[],"strategy":[],"game_news":[]}
Each entry: {"headline":"","summary":"1-2 sentences","so_what":"one sentence: what to do or watch","link":""}
Do not invent facts beyond the item text. If unsure, say so. Items:
"""

def get(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()

def parse(b):
    items = []
    for it in ET.fromstring(b).iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        d = {}
        for c in it:
            t = c.tag.split("}")[-1]
            if t == "title": d["title"] = (c.text or "").strip()
            elif t == "link": d["link"] = (c.text or c.get("href") or "").strip()
            elif t in ("description", "summary") and "text" not in d:
                d["text"] = re.sub("<[^>]+>", " ", c.text or "")[:400]
        if d.get("link") and d.get("title"):
            items.append(d)
    return items

seen = set(json.load(open("seen.json"))) if os.path.exists("seen.json") else set()
new, errors = {}, []
for f in FEEDS:
    try:
        for i in parse(get(f)):
            if i["link"] not in seen:
                new[i["link"]] = i
    except Exception as e:
        errors.append(f"{f}: {e}")
print("Feed errors:", errors)
batch = list(new.values())[:40]
if batch:
    body = json.dumps({"contents": [{"parts": [{"text": PROMPT + json.dumps(batch)}]}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode()
    raw = get(f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
              body, {"Content-Type": "application/json", "x-goog-api-key": KEY})
    out = json.loads(json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"])
    stamp = dt.datetime.utcnow().strftime("%Y-%m-%d-%H%M")
    md = f"# Digest {stamp} UTC\n"
    for cat, entries in out.items():
        if not entries:
            continue
        msg = "\n\n".join(f"{e['headline']}\n{e['summary']}\nSo what: {e['so_what']}\n{e['link']}" for e in entries)
        md += f"\n## {TITLES.get(cat, cat)}\n\n{msg}\n"
        get(f"https://ntfy.sh/{TOPIC}", msg[:3500].encode(),
            {"Title": "WoW Forever - " + TITLES.get(cat, "News"), "Click": entries[0]["link"]})
    os.makedirs("digests", exist_ok=True)
    open(f"digests/{stamp}.md", "w").write(md)
    seen |= {i["link"] for i in batch}
    json.dump(sorted(seen), open("seen.json", "w"))
