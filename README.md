# Pitztal Ice News Monitor

Automatically monitors the [Alpine Adventure news page](https://www.alpine-adventure.at/de/alpine-adventure/alpine-adventure/news.html) for new Pitztal Ice updates, translates them from German to English, and delivers a Telegram notification.

---

## Features

| Feature | Description |
|---|---|
| **Website scraping** | Fetches the news page and extracts the latest item (title, snippet, link). |
| **Change detection** | Compares the latest item against `data/last_seen.json` to avoid duplicate notifications. |
| **Translation** | Translates the German title and snippet to English using Google Translate (via `deep-translator`). |
| **Telegram notification** | Sends a formatted HTML message to a Telegram chat. |
| **Scheduled automation** | Runs every 6 hours via GitHub Actions `cron`. Manual runs are also supported. |

---

## File Structure

```
.
├── .github/workflows/monitor-news.yml  # GitHub Actions workflow (cron + manual trigger)
├── .gitignore                          # Ignores venvs, caches, build artefacts
├── requirements.txt                    # Python dependencies
├── monitor_news.py                     # Main script: scraping, tracking, translating, notifying
├── README.md                           # This file
└── data/
    └── last_seen.json                  # Stores the last-detected news item
```

---

## Setup

### 1. Fork / clone the repository

```bash
git clone https://github.com/<your-user>/pitztal-ice-news-monitor.git
cd pitztal-ice-news-monitor
```

### 2. Create a Telegram bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot` and follow the prompts to get a **bot token**.
3. Start a conversation with your new bot (or add it to a group) and retrieve the **chat ID**
   (you can use `https://api.telegram.org/bot<TOKEN>/getUpdates`).

### 3. Add GitHub Secrets

In your repository go to **Settings → Secrets and variables → Actions → New repository secret**:

| Secret name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The token from BotFather (e.g. `123456:ABCdef…`) |
| `TELEGRAM_CHAT_ID` | Your chat or group ID (e.g. `-1001234567890`) |

### 4. Enable GitHub Actions

The workflow runs automatically. You can also trigger it manually from the **Actions** tab
using the **"Run workflow"** button.

---

## Local development

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run with real secrets
TELEGRAM_BOT_TOKEN=<token> TELEGRAM_CHAT_ID=<chat_id> python monitor_news.py
```

---

## How it works

1. `monitor_news.py` fetches the news page and parses all news items.
2. It loads `data/last_seen.json` and compares the latest item's title/snippet with the stored value.
3. If a new item is detected:
   - The title and snippet are translated from German to English.
   - A Telegram message is sent.
   - `data/last_seen.json` is updated and committed back to the repository by the workflow.
4. If nothing changed, the script exits quietly.

---

## Dependencies

| Package | Purpose |
|---|---|
| `requests` | HTTP requests (page fetch + Telegram API) |
| `beautifulsoup4` | HTML parsing |
| `lxml` | Fast HTML/XML parser backend for BeautifulSoup |
| `deep-translator` | Free Google Translate wrapper |
