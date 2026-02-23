"""
Pitztal Ice News Monitor
Fetches the latest news from the Alpine Adventure website, detects new items,
translates them from German to English, and sends a Telegram notification.
"""

import argparse
import html
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from deep_translator import GoogleTranslator
from deep_translator.exceptions import (
    RequestError,
    TooManyRequests,
    TranslationNotFound,
)

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency for local testing
    load_dotenv = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

if load_dotenv:
    load_dotenv()

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

def _clean_header_text(text: str) -> str:
    """Normalize accordion header text by removing icon labels."""
    if not text:
        return ""
    cleaned = re.sub(r"\b(keyboard_arrow_right|terrain)\b", "", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_date_from_title(title: str) -> date | None:
    """Parse a date from a header like 'Ice News 22.02.2026'."""
    if not title:
        return None
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", title)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_collapsible_items(root: Tag, base_url: str) -> list[dict]:
    """Extract items from the first accordion-style news list."""
    accordion = None
    for heading in root.find_all(["h2", "h3"]):
        heading_text = heading.get_text(" ", strip=True)
        if heading_text.lower().startswith("ice news"):
            accordion = heading.find_next("ul", class_="collapsible")
            if accordion:
                break

    if not accordion:
        accordion = root.find("ul", class_="collapsible")

    if not accordion:
        return []

    items = []
    for entry in accordion.find_all("li", recursive=False):
        header = entry.select_one(".collapsible-header")
        body = entry.select_one(".collapsible-body")

        title = _clean_header_text(header.get_text(" ", strip=True)) if header else ""
        paragraphs = []
        if body:
            for para in body.find_all("p"):
                text = para.get_text(" ", strip=True)
                if text:
                    paragraphs.append(text)
        snippet = "\n\n".join(paragraphs).strip()

        item_date = _extract_date_from_title(title)
        item = {"title": title, "snippet": snippet, "link": base_url, "date": item_date}
        if item["title"] or item["snippet"]:
            items.append(item)

    items.sort(key=lambda item: item.get("date") or date.min, reverse=True)
    for item in items:
        item.pop("date", None)
    return items


def fetch_news(url: str = NEWS_URL) -> list[dict]:
    """Fetch and parse news items from the Alpine Adventure news page.

    Returns a list of dicts with keys: title, snippet, link.
    The list is ordered newest-first as they appear on the page.
    """
    logger.info("Fetching news from %s", url)
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    root: Tag = soup
    collapsible_items = _extract_collapsible_items(root, url)
    if collapsible_items:
        return collapsible_items

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


def translate_long_text(text: str, max_chunk_size: int = 4500) -> str:
    """Translate long text by splitting into chunks to avoid length limits.
    
    Splits text by paragraphs and translates each chunk separately.
    """
    if not text:
        return text
    
    if len(text) <= max_chunk_size:
        return translate_to_english(text)
    
    paragraphs = text.split('\n\n')
    translated: list[str] = []
    current_chunk: list[str] = []
    current_size = 0
    
    for para in paragraphs:
        para_size = len(para)
        if current_size + para_size > max_chunk_size and current_chunk:
            chunk_text = '\n\n'.join(current_chunk)
            translated.append(translate_to_english(chunk_text))
            current_chunk = [para]
            current_size = para_size
        else:
            current_chunk.append(para)
            current_size += para_size + 2
    
    if current_chunk:
        chunk_text = '\n\n'.join(current_chunk)
        translated.append(translate_to_english(chunk_text))
    
    return '\n\n'.join(translated)


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------

def send_telegram_message(message: str) -> None:
    """Send a message to the configured Telegram chat.

    Args:
        message: HTML-formatted text to send.

    Raises:
        requests.HTTPError: If the Telegram API returns an error.
    """
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
    try:
        response.raise_for_status()
    except requests.HTTPError:
        logger.error("Telegram API error response: %s", response.text)
        raise


def _split_message_into_chunks(message: str, title: str, max_length: int = 4000) -> list[str]:
    """Split a message into Telegram-sized chunks with headers.
    
    Each chunk after the first will be prefixed with "TITLE - part N".
    """
    if len(message) <= max_length:
        return [message]
    
    chunks: list[str] = []
    lines = message.split('\n')
    current_chunk: list[str] = []
    current_length = 0
    
    for line in lines:
        line_length = len(line) + 1
        if current_length + line_length > max_length and current_chunk:
            chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_length = line_length
        else:
            current_chunk.append(line)
            current_length += line_length
    
    if current_chunk:
        chunks.append('\n'.join(current_chunk))
    
    for i in range(1, len(chunks)):
        header = f"<b>{html.escape(title)} - part {i + 1}</b>\n\n"
        chunks[i] = header + chunks[i]
    
    return chunks


def send_telegram_messages(item: dict, message: str) -> None:
    """Send message to Telegram, splitting into multiple messages if needed."""
    title = item.get("title", "News Update")
    chunks = _split_message_into_chunks(message, title)
    
    for i, chunk in enumerate(chunks):
        send_telegram_message(chunk)
        if i < len(chunks) - 1:
            # Small delay between messages to maintain order
            import time
            time.sleep(0.5)
    
    if len(chunks) > 1:
        logger.info("Telegram notification sent successfully (%d parts).", len(chunks))
    else:
        logger.info("Telegram notification sent successfully.")


def build_message(item: dict) -> str:
    """Format a Telegram notification message for a news item.

    Translates the title and snippet, applies HTML escaping, and formats
    the message with icons, bold text, and a link.

    Args:
        item: Dictionary with keys 'title', 'snippet', and 'link'.

    Returns:
        HTML-formatted notification message string.
    """
    title_de = item.get("title", "")
    snippet_de = item.get("snippet", "")
    link = item.get("link", "")

    title_en = translate_to_english(title_de)
    snippet_en = translate_long_text(snippet_de)

    title_de_safe = html.escape(title_de)
    title_en_safe = html.escape(title_en)
    snippet_en_safe = html.escape(snippet_en)

    lines = ["🏔 <b>Pitztal Ice – New Update!</b>", ""]
    if title_en_safe:
        lines.append(f"<b>{title_en_safe}</b>")
        if title_de_safe and title_de_safe != title_en_safe:
            lines.append(f"<i>(Original: {title_de_safe})</i>")
        lines.append("")
    if snippet_en_safe:
        lines.append(snippet_en_safe)
        lines.append("")
    if link:
        lines.append(f'<a href="{link}">Read more</a>')

    return "\n".join(lines).strip()


def _strip_html(text: str) -> str:
    """Remove HTML tags for plain-text terminal output."""
    return re.sub(r"<[^>]+>", "", text)


def print_preview(message: str) -> None:
    """Print a plain-text preview of *message* to the terminal."""
    separator = "-" * 60
    print(separator)
    print(_strip_html(message))
    print(separator)


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def main(preview: bool = True, telegram: bool = True) -> None:
    """Fetch news, detect changes, and send notifications.

    Args:
        preview: If True, print translated preview to terminal.
        telegram: If True, send notification via Telegram.
    """
    items = fetch_news()
    if not items:
        logger.info("No news items retrieved. Nothing to do.")
        return

    latest = items[0]
    last_seen = load_last_seen()

    if not is_new(latest, last_seen):
        logger.info("Latest news already pulled. No new updates available.")
        return

    logger.info("New update detected!")
    message = build_message(latest)
    if preview:
        print_preview(message)
    if telegram:
        send_telegram_messages(latest, message)

    save_last_seen(latest)


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Namespace with 'preview' and 'telegram' boolean flags.
    """
    parser = argparse.ArgumentParser(description="Pitztal Ice News Monitor")
    parser.add_argument(
        "--preview",
        dest="preview",
        action="store_true",
        default=True,
        help="Print translated preview to the terminal (default).",
    )
    parser.add_argument(
        "--no-preview",
        dest="preview",
        action="store_false",
        help="Disable terminal preview output.",
    )
    parser.add_argument(
        "--telegram",
        dest="telegram",
        action="store_true",
        default=True,
        help="Send Telegram notification when configured (default).",
    )
    parser.add_argument(
        "--no-telegram",
        dest="telegram",
        action="store_false",
        help="Disable Telegram notification sending.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        args = _parse_args()
        main(preview=args.preview, telegram=args.telegram)
    except requests.HTTPError as exc:
        logger.error("HTTP error: %s", exc)
        sys.exit(1)
    except requests.RequestException as exc:
        logger.error("Network error: %s", exc)
        sys.exit(1)
