import json, os, re, time, urllib.request, urllib.error, datetime as dt
import email.utils
import xml.etree.ElementTree as ET

# (feed url, strict) - strict feeds need "forever" in the title
FEEDS = [
 ("https://blizzardwatch.com/category/warcraft/wow-forever/feed/", False),
 ("https://www.warcrafttavern.com/feed/", True),
 ("https://massivelyop.com/feed/", True),
 ("https://www.wowhead.com/news/rss/all", True),
]
MAX_AGE_DAYS = 4
MAX_PUSH = 8
KEY = os.environ["GEMINI_API_KEY"]
TOPIC = os.environ["NTFY_TOPIC"]
UA = {"User-Agent": "Mozilla/5.0 wow-brief"}
API = "https://generativelanguage.googleapis.com/v1beta/models"
PREFER = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite",
          "gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
          "gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-flash-latest"]
TITLES = {"class_changes": "Class changes", "rankings_sims": "Rankings and sims",
          "auction_house": "Auction House", "strategy": "Gold strategy", "game_news": "Game news"}
PROMPT = """You filter World of Warcraft: Forever news for a busy player.
Use ONLY the items below. Keep items with real substance: hotfix/patch notes, class or spec changes,
balance or tier analysis, sim data, Auction House/economy changes, gold strategies, major announcements.
Drop clickbait, rumors, promos, giveaways, Twitch drops, cosmetic or art updates, boosting or gold-selling ads,
duplicates, weekly roundups or news digests, and anything not mainly about WoW Forever.
Merge duplicate coverage into one entry. Copy each link EXACTLY from the item it came from. Return JSON exactly like:
{"class_changes":[],"rankings_sims":[],"auction_house":[],"strategy":[],"game_news":[]}
Each entry: {"headline":"","summary":"1-2 sentences","so_what":"one sentence: what to do or watch","link":""}
Do not invent facts beyond the item text. If unsure, say so. Items:
"""

def get(url, data=None, headers=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def parse(b):
    items = []
    for it in ET.fromstring(b).iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        d = {}
        for c in it:
            t = c.tag.split("}")[-1]
            if t == "title":
                d["title"] = (c.text or "").strip()
            elif t == "link":
                d["link"] = (c.text or c.get("href") or "").strip()
            elif t in ("description", "summary") and "text" not in d:
                d["text"] = re.sub("<[^>]+>", " ", c.text or "")[:300]
            elif t in ("pubDate", "published", "updated", "date") and "date" not in d:
                d["date"] = (c.text or "").strip()
        if d.get("link") and d.get("title"):
            items.append(d)
    return items

def when(s):
    if not s:
        return None
    try:
        t = email.utils.parsedate_to_datetime(s)
    except Exception:
        try:
            t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t

def pick_models():
    names = []
    try:
        raw = get(API + "?pageSize=200", headers={"x-goog-api-key": KEY})
        for m in json.loads(raw).get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                names.append(m["name"].split("/")[-1])
    except Exception as e:
        print("Model list failed:", e)
    order = [m for m in PREFER if m in names] or PREFER
    print("Will try:", order)
    return order

def save(seen):
    json.dump(sorted(seen), open("seen.json", "w"))

now = dt.datetime.now(dt.timezone.utc)
seen = set(json.load(open("seen.json"))) if os.path.exists("seen.json") else set()
new, skipped, errors = {}, set(), []
for url, strict in FEEDS:
    try:
        for i in parse(get(url)):
            if i["link"] in seen:
                continue
            t = when(i.get("date"))
            old = t is not None and (now - t).days > MAX_AGE_DAYS
            off = strict and "forever" not in i["title"].lower()
            if old or off:
                skipped.add(i["link"])
            else:
                new[i["link"]] = i
    except Exception as e:
        errors.append(url + ": " + str(e))
print("Feed errors:", errors)
batch = list(new.values())[:20]
print("New items:", len(batch), "Skipped:", len(skipped))

if not batch:
    save(seen | skipped)
else:
    body = json.dumps({"contents": [{"parts": [{"text": PROMPT + json.dumps(batch)}]}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode()
    raw = None
    for model in pick_models():
        for attempt in range(2):
            try:
                raw = get(API + "/" + model + ":generateContent", body,
                          {"Content-Type": "application/json", "x-goog-api-key": KEY}, timeout=90)
                print("Used model:", model)
                break
            except urllib.error.HTTPError as e:
                print(model, attempt, e)
                if e.code in (429, 404, 400, 403):
                    break
                time.sleep(8)
            except Exception as e:
                print(model, attempt, e)
                time.sleep(8)
        if raw:
            break
    if not raw:
        raise SystemExit("Gemini unavailable, will retry next run")

    out = json.loads(json.loads(raw)["candidates"][0]["content"]["parts"][0]["text"])
    valid = {i["link"] for i in batch}
    stamp = now.strftime("%Y-%m-%d-%H%M")
    md = "# Digest " + stamp + " UTC\n"
    pushed = 0
    for cat, entries in out.items():
        entries = [e for e in entries if e.get("link") in valid]
        if not entries:
            continue
        md += "\n## " + TITLES.get(cat, cat) + "\n"
        for e in entries:
            msg = e["headline"] + "\n" + e["summary"] + "\nSo what: " + e["so_what"]
            md += "\n" + msg + "\n" + e["link"] + "\n"
            if pushed < MAX_PUSH:
                try:
                    get("https://ntfy.sh/" + TOPIC, msg[:1500].encode(),
                        {"Title": "WoW Forever - " + TITLES.get(cat, "News"), "Click": e["link"]})
                    pushed += 1
                except Exception as ex:
                    print("Push failed:", ex)
    print("Pushed:", pushed)
    os.makedirs("digests", exist_ok=True)
    open("digests/" + stamp + ".md", "w").write(md)
    save(seen | skipped | valid)
