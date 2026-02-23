"""Unit tests for monitor_news.py.

All external I/O (HTTP, filesystem, Google Translate) is mocked so the
tests run fully offline without real credentials.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

import monitor_news


# ---------------------------------------------------------------------------
# is_new
# ---------------------------------------------------------------------------

def test_is_new_empty_last_seen():
    assert monitor_news.is_new({"title": "News"}, {}) is True


def test_is_new_same_item():
    item = {"title": "News", "snippet": "Hello"}
    assert monitor_news.is_new(item, item.copy()) is False


def test_is_new_changed_title():
    assert monitor_news.is_new({"title": "B", "snippet": "x"}, {"title": "A", "snippet": "x"}) is True


def test_is_new_changed_snippet():
    assert monitor_news.is_new({"title": "A", "snippet": "new"}, {"title": "A", "snippet": "old"}) is True


# ---------------------------------------------------------------------------
# load_last_seen / save_last_seen
# ---------------------------------------------------------------------------

def test_load_last_seen_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    assert monitor_news.load_last_seen() == {}


def test_load_last_seen_reads_file(tmp_path, monkeypatch):
    f = tmp_path / "last_seen.json"
    f.write_text('{"title": "T", "snippet": "S"}', encoding="utf-8")
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", f)
    assert monitor_news.load_last_seen() == {"title": "T", "snippet": "S"}


def test_load_last_seen_corrupt_file(tmp_path, monkeypatch):
    f = tmp_path / "last_seen.json"
    f.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", f)
    assert monitor_news.load_last_seen() == {}


def test_save_and_reload(tmp_path, monkeypatch):
    f = tmp_path / "last_seen.json"
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", f)
    item = {"title": "T", "snippet": "S", "link": "https://example.com"}
    monitor_news.save_last_seen(item)
    assert json.loads(f.read_text(encoding="utf-8")) == item
    assert monitor_news.load_last_seen() == item


# ---------------------------------------------------------------------------
# translate_to_english
# ---------------------------------------------------------------------------

def test_translate_empty_string():
    assert monitor_news.translate_to_english("") == ""


def test_translate_success():
    with patch("monitor_news.GoogleTranslator") as mock_cls:
        mock_cls.return_value.translate.return_value = "Hello"
        result = monitor_news.translate_to_english("Hallo")
    assert result == "Hello"


def test_translate_falls_back_on_translation_not_found():
    from deep_translator.exceptions import TranslationNotFound

    with patch("monitor_news.GoogleTranslator") as mock_cls:
        mock_cls.return_value.translate.side_effect = TranslationNotFound("x")
        result = monitor_news.translate_to_english("Hallo")
    assert result == "Hallo"


def test_translate_falls_back_on_request_error():
    from deep_translator.exceptions import RequestError

    with patch("monitor_news.GoogleTranslator") as mock_cls:
        mock_cls.return_value.translate.side_effect = RequestError()
        result = monitor_news.translate_to_english("Hallo")
    assert result == "Hallo"


def test_translate_falls_back_on_too_many_requests():
    from deep_translator.exceptions import TooManyRequests

    with patch("monitor_news.GoogleTranslator") as mock_cls:
        mock_cls.return_value.translate.side_effect = TooManyRequests()
        result = monitor_news.translate_to_english("Hallo")
    assert result == "Hallo"


def test_translate_falls_back_on_unexpected_error():
    with patch("monitor_news.GoogleTranslator") as mock_cls:
        mock_cls.return_value.translate.side_effect = RuntimeError("boom")
        result = monitor_news.translate_to_english("Hallo")
    assert result == "Hallo"


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------

def test_build_message_contains_header():
    with patch("monitor_news.translate_to_english", side_effect=lambda t: t):
        msg = monitor_news.build_message({"title": "T", "snippet": "S", "link": "https://x.com"})
    assert "Pitztal Ice" in msg
    assert "<b>T</b>" in msg
    assert "S" in msg
    assert '<a href="https://x.com">Read more</a>' in msg


def test_build_message_shows_original_when_translated():
    def fake_translate(text):
        return "English" if text == "Deutsch" else text

    with patch("monitor_news.translate_to_english", side_effect=fake_translate):
        msg = monitor_news.build_message({"title": "Deutsch", "snippet": "", "link": ""})
    assert "<b>English</b>" in msg
    assert "<i>(Original: Deutsch)</i>" in msg


def test_build_message_no_original_when_same():
    with patch("monitor_news.translate_to_english", side_effect=lambda t: t):
        msg = monitor_news.build_message({"title": "Same", "snippet": "", "link": ""})
    assert "(Original:" not in msg


def test_build_message_empty_item():
    with patch("monitor_news.translate_to_english", side_effect=lambda t: t):
        msg = monitor_news.build_message({})
    assert "Pitztal Ice" in msg


# ---------------------------------------------------------------------------
# fetch_news
# ---------------------------------------------------------------------------

_SAMPLE_HTML = """
<html><body>
  <article>
    <h2>Breaking News</h2>
    <p>Something happened.</p>
    <a href="/news/1">Read</a>
  </article>
  <article>
    <h2>Old News</h2>
    <p>Old stuff.</p>
    <a href="https://example.com/2">Link</a>
  </article>
</body></html>
"""


def test_fetch_news_parses_articles():
    mock_resp = MagicMock()
    mock_resp.text = _SAMPLE_HTML
    mock_resp.raise_for_status.return_value = None

    with patch("monitor_news.requests.get", return_value=mock_resp):
        items = monitor_news.fetch_news("https://example.com/news")

    assert len(items) == 2
    assert items[0]["title"] == "Breaking News"
    assert items[0]["snippet"] == "Something happened."
    assert items[0]["link"] == "https://example.com/news/1"
    assert items[1]["link"] == "https://example.com/2"


def test_fetch_news_empty_page():
    mock_resp = MagicMock()
    mock_resp.text = "<html><body></body></html>"
    mock_resp.raise_for_status.return_value = None

    with patch("monitor_news.requests.get", return_value=mock_resp):
        items = monitor_news.fetch_news("https://example.com/news")

    assert items == []


# ---------------------------------------------------------------------------
# send_telegram_message
# ---------------------------------------------------------------------------

def test_send_telegram_skips_when_no_token(monkeypatch):
    monkeypatch.setattr(monitor_news, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(monitor_news, "TELEGRAM_CHAT_ID", "123")
    with patch("monitor_news.requests.post") as mock_post:
        monitor_news.send_telegram_message("hello")
    mock_post.assert_not_called()


def test_send_telegram_posts_message(monkeypatch):
    monkeypatch.setattr(monitor_news, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(monitor_news, "TELEGRAM_CHAT_ID", "123")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None

    with patch("monitor_news.requests.post", return_value=mock_resp) as mock_post:
        monitor_news.send_telegram_message("hello")

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["text"] == "hello"
    assert kwargs["json"]["chat_id"] == "123"


# ---------------------------------------------------------------------------
# main (integration-style with all I/O mocked)
# ---------------------------------------------------------------------------

def test_main_sends_notification_for_new_item(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    monkeypatch.setattr(monitor_news, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(monitor_news, "TELEGRAM_CHAT_ID", "123")

    item = {"title": "New", "snippet": "Snip", "link": "https://x.com"}

    with (
        patch("monitor_news.fetch_news", return_value=[item]),
        patch("monitor_news.translate_to_english", side_effect=lambda t: t),
        patch("monitor_news.requests.post", return_value=MagicMock(raise_for_status=lambda: None)) as mock_post,
    ):
        monitor_news.main()

    mock_post.assert_called_once()
    assert monitor_news.load_last_seen() == item


def test_main_no_notification_for_seen_item(tmp_path, monkeypatch):
    item = {"title": "Old", "snippet": "Snip", "link": "https://x.com"}
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    monitor_news.save_last_seen(item)

    with (
        patch("monitor_news.fetch_news", return_value=[item]),
        patch("monitor_news.requests.post") as mock_post,
    ):
        monitor_news.main()

    mock_post.assert_not_called()


def test_main_no_items(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    with (
        patch("monitor_news.fetch_news", return_value=[]),
        patch("monitor_news.requests.post") as mock_post,
    ):
        monitor_news.main()
    mock_post.assert_not_called()
