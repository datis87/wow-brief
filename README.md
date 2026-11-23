# WoW Forever Brief

A free, self-hosted news filter for **World of Warcraft: Forever**. It reads RSS feeds on a schedule, has an AI model drop clickbait and sort stories into categories, and pushes short summaries to your phone. It also publishes a small mobile-friendly page you can filter.

No server, no paid services. It runs on GitHub Actions, the Gemini API free tier, and ntfy.

## How it works

1. **GitHub Actions** runs `filter.py` on a schedule.
2. The script pulls RSS feeds, skips stories it has already seen, and drops anything older than 4 days. Feeds marked strict must have "forever" in the title.
3. **Gemini** filters out promos and fluff, sorts stories into five categories, and writes a summary and a "so what" line for each.
4. **ntfy** pushes each story to a per-category topic on your phone.
5. The script saves a digest in `digests/` and updates `docs/data.json`, which feeds the page in `docs/index.html` (GitHub Pages).

## Categories

| Category | ntfy topic suffix |
|---|---|
| Class changes (all hotfixes and patch notes) | `-class` |
| Auction House | `-ah` |
| Rankings and sims | `-rankings` |
| Gold strategy | `-strategy` |
| Game news | `-news` |

The base topic carries only a "More stories" notification when a category exceeds 4 pushes in one run.

## Setup (works from a phone)

On a phone, use your browser's **Desktop site** mode. GitHub's file editor works poorly in mobile view.

### 1. Fork or copy the repo

Fork this repo, or create a new **public** repo and copy the files in. A public repo gives you free Actions minutes and free Pages hosting.

### 2. Get a Gemini API key

Go to [aistudio.google.com](https://aistudio.google.com), sign in, and choose **Get API key**. Keep it private.

### 3. Set up ntfy

1. Install the **ntfy** app (Android or iOS).
2. Pick a long random base topic name, for example `wowfv-k7x92qm4p1`. Anyone who knows a topic name can read and post to it, so do not use a guessable one.
3. Subscribe to the category topics you want: `<base>-class`, `<base>-ah`, `<base>-rankings`, `<base>-strategy`, `<base>-news`, plus the base topic itself for "More" alerts.
4. On Android, set ntfy to unrestricted battery use so notifications are not delayed.

### 4. Add repository secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret | Value |
|---|---|
| `GEMINI_API_KEY` | your Gemini key |
| `NTFY_TOPIC` | your base topic, with no spaces and the exact same spelling as in the app |

Never commit these values to a file.

### 5. Edit two settings in `filter.py`

```python
PAGE_URL = "https://YOUR-USERNAME.github.io/YOUR-REPO/"
```

Change `PAGE_URL` to your own Pages address. It is the link behind the "More stories" notification.

Optionally adjust:

| Setting | Meaning |
|---|---|
| `FEEDS` | RSS sources. `True` means a story's title must contain "forever". |
| `MAX_AGE_DAYS` | Ignore stories older than this. Default 4. |
| `MAX_PER_CAT` | Maximum pushes per category per run. Default 4. |
| `PROMPT` | The filter and category rules. Edit this to change what counts as relevant. |

### 6. Workflow file

Create `.github/workflows/brief.yml`:

```yaml
name: wow-brief
on:
  schedule:
    - cron: "0 7,11,16 * * *"
  workflow_dispatch:
permissions:
  contents: write
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 filter.py
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}
      - run: |
          git config user.name "wow-brief"
          git config user.email "bot@users.noreply.github.com"
          git add -A
          git diff --cached --quiet || (git commit -m "digest" && git push)
```

Cron times are in **UTC**. The example runs at 07:00, 11:00 and 16:00 UTC, which is 09:00, 13:00 and 18:00 in Finland during winter time. Convert for your own time zone, and remember daylight saving changes shift your local time by an hour.

### 7. Turn on the page

Go to **Settings → Pages**, set **Source** to **Deploy from a branch**, branch **main**, folder **/docs**, and save. Your page appears at the address you set in `PAGE_URL`.

### 8. Run it once

Go to **Actions → wow-brief → Run workflow**. Notifications and the page should appear within a minute or two.

## Using the page

- Tap category chips to hide or show categories.
- Type keywords separated by commas to show only matching stories. Prefix a word with `-` to hide matches, for example `paladin, hotfix` or `-pvp`.
- Your choices are saved in your own browser only. They change what you see on the page, not what is pushed. To change what is pushed, mute topics in ntfy or edit the prompt.

## Free tier and limits

- **GitHub Actions** is free for public repos. In a public repo, scheduled workflows are disabled after 60 days without repo activity. The bot's own digest commits count as activity, so this normally keeps itself alive.
- **Gemini free tier** limits and model names change over time, and models can be overloaded. The script lists the models your key can use and tries lightweight ones first. Free-tier prompts may be used by Google to improve its products, which is fine for public news but do not send private data.
- If every model fails, the run exits with an error and the next scheduled run retries. Nothing is lost, because stories are only marked as seen after a successful run.

## Forking notes

- Scheduled workflows are **disabled by default in forks**. Open the **Actions** tab and enable workflows, then trigger one run manually.
- The repo, digests and `data.json` are public. They contain only public news, but do not put secrets in any file.
- To reset the history, delete `seen.json`. The next run then reprocesses stories newer than `MAX_AGE_DAYS`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Run succeeds but no notifications | `NTFY_TOPIC` does not exactly match the topic in the app. Re-enter it with no spaces. |
| `Gemini unavailable` | Models are busy or rate limited. Wait for the next run. |
| `HTTP 404` on a feed | The feed address changed. Replace it in `FEEDS`. |
| `HTTP 404` on a model | Model names retire. The script's model list handles this automatically. |
| Workflow does not fire on schedule | GitHub timers can run a few minutes late. Check that workflows are enabled. |
| Page says "No data yet" | The workflow has not completed a successful run with new stories. |
| Wrong category | Adjust the category rules in `PROMPT`. |

## Credits and disclaimer

Story summaries are written by an AI model and can be wrong. Always read the linked article before acting on anything, especially gold-related decisions. Not affiliated with Blizzard Entertainment.
