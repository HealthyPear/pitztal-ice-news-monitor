# Pitztal Ice News Monitor

[![CI](https://github.com/HealthyPear/pitztal-ice-news-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/HealthyPear/pitztal-ice-news-monitor/actions/workflows/ci.yml)
[![Monitoring workflow](https://img.shields.io/github/actions/workflow/status/HealthyPear/pitztal-ice-news-monitor/monitor-news.yml?branch=main&label=Monitoring%20workflow)](https://github.com/HealthyPear/pitztal-ice-news-monitor/actions/workflows/monitor-news.yml)
[![Python](https://img.shields.io/badge/dynamic/toml?url=https://raw.githubusercontent.com/HealthyPear/pitztal-ice-news-monitor/main/pixi.toml&query=$.dependencies.python&label=python&color=blue)](https://www.python.org/downloads/)
[![pixi](https://img.shields.io/badge/pixi-enabled-2bb673.svg)](https://pixi.sh/)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Telegram](https://img.shields.io/badge/telegram-channel-2CA5E0?logo=telegram&logoColor=white)](https://t.me/+6rJDCEqZPeQ3N2Vk)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

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

## Join the Telegram channel

Pitztal Ice News: https://t.me/+6rJDCEqZPeQ3N2Vk

## How to contribute

Did you find a mistake or you have in mind a new feature?

### 0. Fork / clone the repository

```bash
git clone https://github.com/<your-user>/pitztal-ice-news-monitor.git
cd pitztal-ice-news-monitor
```

### 1. Install pixi

Follow the [official instructions](https://pixi.sh/latest/#installation):

```bash
# macOS / Linux
curl -fsSL https://pixi.sh/install.sh | sh

# Windows (PowerShell)
iwr -useb https://pixi.sh/install.ps1 | iex
```

### 2. Switch to a new branch

```bash
git switch -c use/a/meaningful/name
```

### 3. Install the environment

```bash
pixi install
```

This resolves all dependencies and creates an isolated environment under `.pixi/`.

### 4. Run the current unit tests (no credentials needed)

```bash
pixi run -e dev test
```

All 25 tests mock external I/O, so they run fully offline and require no Telegram token or internet access.

### 5. Run the monitor script locally

```bash
# Preview only (no Telegram)
pixi run monitor --no-telegram

# Full run with Telegram (requires .env credentials)
pixi run monitor
```



> **Tip – force a notification on the first run:**
> The script only sends a message when the latest item differs from what is stored in
> `data/last_seen.json`. To guarantee a notification, reset the file before running:
>
> ```bash
> echo '{}' > data/last_seen.json
> ```

---

## How it works

1. `monitor_news.py` fetches the news page and parses all news items.
2. It loads `data/last_seen.json` and compares the latest item's title/snippet with the stored value.
3. If a new item is detected:
   - The title and snippet are translated from German to English (in chunks to handle long text).
   - A Telegram message is sent (split into multiple messages if needed).
   - `data/last_seen.json` is updated.
4. If nothing changed, the script exits quietly.

When run via GitHub Actions, the state is cached between runs so duplicate notifications are avoided.

---

## Dependencies

All dependencies are declared in `pixi.toml`.

| Package | Purpose |
|---|---|
| `requests` | HTTP requests (page fetch + Telegram API) |
| `beautifulsoup4` | HTML parsing |
| `lxml` | Fast HTML/XML parser backend for BeautifulSoup |
| `deep-translator` | Free Google Translate wrapper |
| `python-dotenv` *(optional)* | Load credentials from `.env` file for local testing |
| `pytest` *(dev)* | Unit testing |
