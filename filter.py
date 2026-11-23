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
MAX_PER_TOPIC = 3
MAX_PARENT = 6
KEEP = 400
FULLTEXT_MAX = 6
PAGE_URL = "https://datis87.github.io/wow-brief/"
CLASSES = ["Druid", "Hunter", "Mage", "Paladin", "Priest", "Rogue", "Shaman", "Warlock", "Warrior"]
KEY = os.environ["GEMINI_API_KEY"]
TOPIC = os.environ["NTFY_TOPIC"]
UA = {"User-Agent": "Mozilla/5.0 wow-brief"}
API = "https://generativelanguage.googleapis.com/v1beta/models"
PREFER = ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash-lite",
          "gemini-2.5-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.7-flash",
          "gemini-3.8-flash", "gemini-flash-lite-latest", "gemini-flash-latest"]
ORDER = ["class_changes", "auction_house", "rankings_sims", "strategy", "game_news"]
TITLES = {"class_changes": "Class changes", "rankings_sims": "Rankings and sims",
          "auction_house": "Auction House", "strategy": "Gold strategy", "game_news": "Game news"}
SUFFIX = {"class_changes": "class", "auction_house": "ah", "rankings_sims": "rankings",
          "strategy": "strategy", "game_news": "news"}
PROMPT = """You filter World of Warcraft: Forever news for a busy player.
Use ONLY the items below. Keep items with real substance. Drop clickbait, rumors, promos, giveaways,
Twitch drops, cosmetic or art updates, boosting or gold-selling ads, duplicates, weekly roundups or
news digests, and anything not mainly about WoW Forever. Merge duplicate coverage into one entry.
Put each kept item in exactly ONE category using these strict rules:
- class_changes: ALL hotfix and patch notes (including bug fixes and exploit fixes), plus any class, spec,
  talent, racial ability, or itemization change.
  For this category output ONE entry PER AFFECTED CLASS, even when they share the same link.
  Set "class" to exactly one of: Druid, Hunter, Mage, Paladin, Priest, Rogue, Shaman, Warlock, Warrior,
  or General (for changes not tied to one class, such as dungeons, items, quests, or system bug fixes).
  The summary must contain ONLY that class's changes, naming the spell or talent and what changed.
  Never guess changes the item text does not state.
- rankings_sims: tier lists, class or spec rankings, sim results, DPS or healing comparisons, PvP rankings.
- auction_house: ONLY auction house rules, fees, listings, or market prices of tradable items.
  Vendor prices, mount discounts and gold sinks are NOT auction house.
- strategy: gold-making, farming, professions and crafting, leveling routes, how-to advice, vendor or mount costs.
- game_news: announcements, roadmap, new content, milestones, server or system rules such as addon or
  layering rules. Use this only when no other category fits.
Copy each link EXACTLY from the item it came from. Return JSON exactly like:
{"class_changes":[{"class":"Paladin","headline":"","summary":"","so_what":"","link":""}],
"auction_house":[],"rankings_sims":[],"strategy":[],"game_news":[]}
Entries in other categories have no "class" field. Each entry has headline, summary (1-2 sentences),
so_what (one sentence: what to do or watch), and link.
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

def fulltext(url):
    try:
        h = get(url, timeout=30).decode("utf-8", "ignore")
        h = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", h)
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
        return t[:5000]
    except Exception as e:
        print("Fulltext failed:", url, e)
        return ""

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

def push(suffix, title, msg, link):
    topic = TOPIC + ("-" + suffix if suffix else "")
    get("https://ntfy.sh/" + topic, msg[:1500].encode(), {"Title": title, "Click": link})

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

fetched = 0
for i in batch:
    if fetched >= FULLTEXT_MAX:
        break
    if re.search(r"hotfix|patch|class|balance|changes|update", i["title"], re.I):
        full = fulltext(i["link"])
        if len(full) > 400:
            i["text"] = full
        fetched += 1
print("Full texts fetched:", fetched)

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
                          {"Content-Type": "application/json", "x-goog-api-key": KEY}, timeout=120)
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
    items, done = [], set()
    for cat in ORDER + [c for c in out if c not in ORDER]:
        md_head = False
        for e in out.get(cat, []):
            if e.get("link") not in valid:
                continue
            cls = ""
            if cat == "class_changes":
                cls = str(e.get("class", "General")).strip().title()
                if cls not in CLASSES:
                    cls = "General"
            key = (e["link"], cls)
            if key in done:
                continue
            done.add(key)
            if not md_head:
                md += "\n## " + TITLES.get(cat, cat) + "\n"
                md_head = True
            tag = "[" + cls + "] " if cls else ""
            md += "\n" + tag + e["headline"] + "\n" + e["summary"] + "\nSo what: " + e["so_what"] + "\n" + e["link"] + "\n"
            items.append((cat, cls, e))

    counts, extra, pushed = {}, 0, 0
    for cat, cls, e in items:
        msg = e["headline"] + "\n" + e["summary"] + "\nSo what: " + e["so_what"]
        if cat == "class_changes":
            targets = [("class", "WoW Forever - Class changes (" + cls + ")", MAX_PARENT)]
            if cls in CLASSES:
                targets.append(("class-" + cls.lower(), "WoW Forever - " + cls, MAX_PER_TOPIC))
        else:
            targets = [(SUFFIX.get(cat, "news"), "WoW Forever - " + TITLES.get(cat, "News"), MAX_PER_TOPIC)]
        sent = False
        for suffix, title, cap in targets:
            if counts.get(suffix, 0) >= cap:
                continue
            try:
                push(suffix, title, msg, e["link"])
                counts[suffix] = counts.get(suffix, 0) + 1
                pushed += 1
                sent = True
            except Exception as ex:
                print("Push failed:", ex)
        if not sent:
            extra += 1
    if extra > 0:
        try:
            push("", "WoW Forever - More", str(extra) + " more stories on the page. Tap to open.", PAGE_URL)
        except Exception as ex:
            print("Push failed:", ex)
    print("Pushed:", pushed, "Extra:", extra)

    os.makedirs("digests", exist_ok=True)
    open("digests/" + stamp + ".md", "w").write(md)
    os.makedirs("docs", exist_ok=True)
    old_entries = []
    try:
        old_entries = json.load(open("docs/data.json")).get("entries", [])
    except Exception:
        pass
    ts = now.isoformat()
    fresh = [{"ts": ts, "cat": c, "cls": k, "headline": e["headline"], "summary": e["summary"],
              "so_what": e["so_what"], "link": e["link"]} for c, k, e in items]
    merged, keys = [], set()
    for x in fresh + old_entries:
        kk = x["link"] + "|" + x.get("cls", "")
        if kk not in keys:
            keys.add(kk)
            merged.append(x)
    json.dump({"updated": ts, "entries": merged[:KEEP]}, open("docs/data.json", "w"))
    save(seen | skipped | valid)
