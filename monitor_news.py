"""
Pitztal Ice News Monitor
Fetches the latest news from the Alpine Adventure website, detects new items,
translates them from German to English, and sends a Telegram notification.
"""

import json
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from deep_translator.exceptions import (
    RequestError,
    TooManyRequests,
    TranslationNotFound,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NEWS_URL = (
    "https://www.alpine-adventure.at/de/alpine-adventure/alpine-adventure/news.html"
)
LAST_SEEN_FILE = Path(__file__).parent / "data" / "last_seen.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"

REQUEST_TIMEOUT = 30  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def fetch_news(url: str = NEWS_URL) -> list[dict]:
    """Fetch and parse news items from the Alpine Adventure news page.

    Returns a list of dicts with keys: title, snippet, link.
    The list is ordered newest-first as they appear on the page.
    """
    logger.info("Fetching news from %s", url)
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    items = []

    # The page uses <article> elements or generic news-list containers.
    # We try several common selectors in order of preference.
    candidates = (
        soup.select("article.news-item")
        or soup.select("article")
        or soup.select(".news-list-item")
        or soup.select(".news-item")
        or soup.select(".teaser")
    )

    for article in candidates:
        title_tag = (
            article.find(["h1", "h2", "h3", "h4"])
            or article.find(class_=lambda c: c and "title" in c.lower())
        )
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Snippet: first paragraph or dedicated summary element
        snippet_tag = article.find("p") or article.find(
            class_=lambda c: c and ("teaser" in c.lower() or "summary" in c.lower())
        )
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

        link_tag = article.find("a", href=True)
        href = link_tag["href"] if link_tag else ""
        if href and not href.startswith("http"):
            href = urljoin(url, href)

        if title or snippet:
            items.append({"title": title, "snippet": snippet, "link": href})

    if not items:
        logger.warning("No news items found – the page structure may have changed.")

    return items


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def load_last_seen() -> dict:
    """Load the last-seen news item from disk."""
    if LAST_SEEN_FILE.exists():
        try:
            with LAST_SEEN_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read %s: %s", LAST_SEEN_FILE, exc)
    return {}


def save_last_seen(item: dict) -> None:
    """Persist the most-recently-seen news item to disk."""
    LAST_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LAST_SEEN_FILE.open("w", encoding="utf-8") as fh:
        json.dump(item, fh, ensure_ascii=False, indent=2)
    logger.info("Saved last-seen item to %s", LAST_SEEN_FILE)


def is_new(item: dict, last_seen: dict) -> bool:
    """Return True when *item* differs from the stored *last_seen* entry."""
    return (item.get("title") != last_seen.get("title")) or (
        item.get("snippet") != last_seen.get("snippet")
    )


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

def translate_to_english(text: str) -> str:
    """Translate *text* from German to English using Google Translate.

    Falls back to the original text if translation fails.
    """
    if not text:
        return text
    try:
        translated = GoogleTranslator(source="de", target="en").translate(text)
        return translated or text
    except TranslationNotFound:
        logger.warning("Translation not found for text: %.80s", text)
        return text
    except TooManyRequests:
        logger.warning("Translation rate-limited; returning original text.")
        return text
    except RequestError as exc:
        logger.warning("Translation request error: %s", exc)
        return text
    except Exception as exc:  # noqa: BLE001 – catch-all for unexpected translator errors
        logger.warning("Translation failed unexpectedly: %s", exc)
        return text


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------

def send_telegram_message(message: str) -> None:
    """Send *message* to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set. "
            "Skipping Telegram notification."
        )
        return

    url = TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    logger.info("Telegram notification sent successfully.")


def build_message(item: dict) -> str:
    """Format a Telegram notification message for *item*."""
    title_de = item.get("title", "")
    snippet_de = item.get("snippet", "")
    link = item.get("link", "")

    title_en = translate_to_english(title_de)
    snippet_en = translate_to_english(snippet_de)

    lines = ["🏔 <b>Pitztal Ice – New Update!</b>", ""]
    if title_en:
        lines.append(f"<b>{title_en}</b>")
        if title_de and title_de != title_en:
            lines.append(f"<i>(Original: {title_de})</i>")
        lines.append("")
    if snippet_en:
        lines.append(snippet_en)
        lines.append("")
    if link:
        lines.append(f'<a href="{link}">Read more</a>')

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    items = fetch_news()
    if not items:
        logger.info("No news items retrieved. Nothing to do.")
        return

    latest = items[0]
    last_seen = load_last_seen()

    if is_new(latest, last_seen):
        logger.info("New news item detected: %s", latest.get("title"))
        message = build_message(latest)
        send_telegram_message(message)
        save_last_seen(latest)
    else:
        logger.info("No new news items. Latest item already seen.")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        logger.error("HTTP error: %s", exc)
        sys.exit(1)
    except requests.RequestException as exc:
        logger.error("Network error: %s", exc)
        sys.exit(1)
