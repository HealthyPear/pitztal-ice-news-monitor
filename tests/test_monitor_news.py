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
# translate_long_text
# ---------------------------------------------------------------------------

def test_translate_long_text_short_text():
    """Short text should use regular translation without chunking."""
    with patch("monitor_news.translate_to_english", return_value="Hello") as mock_translate:
        result = monitor_news.translate_long_text("Hallo")
    assert result == "Hello"
    mock_translate.assert_called_once_with("Hallo")


def test_translate_long_text_chunks_long_text():
    """Long text should be chunked and translated separately."""
    # Create text > 4500 chars with multiple paragraphs
    long_text = "\n\n".join(["Para " + str(i) + " " + "x" * 1000 for i in range(6)])
    
    with patch("monitor_news.translate_to_english", side_effect=lambda t: t.upper()) as mock_translate:
        result = monitor_news.translate_long_text(long_text)
    
    # Should have called translate multiple times (chunked)
    assert mock_translate.call_count > 1
    # Result should be uppercase (our fake translation)
    assert "PARA" in result


# ---------------------------------------------------------------------------
# _split_message_into_chunks
# ---------------------------------------------------------------------------

def test_split_message_short_message():
    """Short message should not be split."""
    msg = "Short message"
    chunks = monitor_news._split_message_into_chunks(msg, "Title")
    assert len(chunks) == 1
    assert chunks[0] == msg


def test_split_message_long_message():
    """Long message should be split with headers."""
    # Create a message > 4000 chars
    msg = "Line\n" * 500  # 2500 chars
    chunks = monitor_news._split_message_into_chunks(msg, "Test Title", max_length=1000)
    
    assert len(chunks) > 1
    # First chunk should not have header added
    assert chunks[0].startswith("Line")
    # Subsequent chunks should have headers
    for i in range(1, len(chunks)):
        assert f"Test Title - part {i + 1}" in chunks[i]


# ---------------------------------------------------------------------------
# build_message
# ---------------------------------------------------------------------------

def test_build_message_contains_header():
    with (
        patch("monitor_news.translate_to_english", side_effect=lambda t: t),
        patch("monitor_news.translate_long_text", side_effect=lambda t: t),
    ):
        msg = monitor_news.build_message({"title": "T", "snippet": "S", "link": "https://x.com"})
    assert "Pitztal Ice" in msg
    assert "<b>T</b>" in msg
    assert "S" in msg
    assert '<a href="https://x.com">Read more</a>' in msg


def test_build_message_shows_original_when_translated():
    def fake_translate(text):
        return "English" if text == "Deutsch" else text

    with (
        patch("monitor_news.translate_to_english", side_effect=fake_translate),
        patch("monitor_news.translate_long_text", side_effect=lambda t: t),
    ):
        msg = monitor_news.build_message({"title": "Deutsch", "snippet": "", "link": ""})
    assert "<b>English</b>" in msg
    assert "<i>(Original: Deutsch)</i>" in msg


def test_build_message_no_original_when_same():
    with (
        patch("monitor_news.translate_to_english", side_effect=lambda t: t),
        patch("monitor_news.translate_long_text", side_effect=lambda t: t),
    ):
        msg = monitor_news.build_message({"title": "Same", "snippet": "", "link": ""})
    assert "(Original:" not in msg


def test_build_message_empty_item():
    with (
        patch("monitor_news.translate_to_english", side_effect=lambda t: t),
        patch("monitor_news.translate_long_text", side_effect=lambda t: t),
    ):
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

_COLLAPSIBLE_HTML = """
<html><body>
    <h2>Ice News 2025/26</h2>
    <ul class="collapsible">
        <li>
            <div class="collapsible-header"><h3><i class="material-icons left">keyboard_arrow_right</i>Ice News 22.02.2026</h3></div>
            <div class="collapsible-body">
                <p>Hallo Leute,</p>
                <p>Die Strassensperre wird aufgehoben.</p>
            </div>
        </li>
        <li>
            <div class="collapsible-header"><h3>Ice News 01.11.2025</h3></div>
            <div class="collapsible-body"><p>Older update.</p></div>
        </li>
    </ul>
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


def test_fetch_news_parses_collapsible_list():
    mock_resp = MagicMock()
    mock_resp.text = _COLLAPSIBLE_HTML
    mock_resp.raise_for_status.return_value = None

    with patch("monitor_news.requests.get", return_value=mock_resp):
        items = monitor_news.fetch_news("https://example.com/news")

    assert len(items) == 2
    assert items[0]["title"] == "Ice News 22.02.2026"
    assert "Hallo Leute" in items[0]["snippet"]
    assert items[1]["title"] == "Ice News 01.11.2025"


def test_fetch_news_empty_page():
    mock_resp = MagicMock()
    mock_resp.text = "<html><body></body></html>"
    mock_resp.raise_for_status.return_value = None

    with patch("monitor_news.requests.get", return_value=mock_resp):
        items = monitor_news.fetch_news("https://example.com/news")

    assert items == []


# ---------------------------------------------------------------------------
# main (integration-style with all I/O mocked)
# ---------------------------------------------------------------------------

def test_main_prints_preview_for_latest_item(capsys):
    item = {"title": "New", "snippet": "Snip", "link": "https://x.com"}

    with (
        patch("monitor_news.fetch_news", return_value=[item]),
        patch("monitor_news.translate_to_english", side_effect=lambda t: t),
        patch("monitor_news.translate_long_text", side_effect=lambda t: t),
        patch("monitor_news.load_last_seen", return_value={}),
        patch("monitor_news.send_telegram_messages"),
        patch("monitor_news.save_last_seen"),
    ):
        monitor_news.main()

    captured = capsys.readouterr()
    assert "New" in captured.out
    assert "Snip" in captured.out
    assert "<b>" not in captured.out


def test_main_no_items(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    with (
        patch("monitor_news.fetch_news", return_value=[]),
    ):
        monitor_news.main()


def test_main_new_item_sends_and_saves(tmp_path, monkeypatch, capsys):
    """Test that a new item triggers notification and gets saved."""
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    item = {"title": "New News", "snippet": "Fresh content", "link": "https://x.com"}
    last_seen = {"title": "Old News", "snippet": "Old content", "link": "https://x.com"}

    with (
        patch("monitor_news.fetch_news", return_value=[item]),
        patch("monitor_news.translate_to_english", side_effect=lambda t: t),
        patch("monitor_news.translate_long_text", side_effect=lambda t: t),
        patch("monitor_news.load_last_seen", return_value=last_seen),
        patch("monitor_news.send_telegram_messages") as mock_telegram,
        patch("monitor_news.save_last_seen") as mock_save,
    ):
        monitor_news.main(preview=True, telegram=True)

    # Should send telegram and save
    mock_telegram.assert_called_once()
    mock_save.assert_called_once_with(item)

    # Should show preview
    captured = capsys.readouterr()
    assert "New News" in captured.out


def test_main_already_pulled_skips_notification(tmp_path, monkeypatch, capsys):
    """Test that an already-seen item does not trigger notification."""
    monkeypatch.setattr(monitor_news, "LAST_SEEN_FILE", tmp_path / "last_seen.json")
    item = {"title": "Same News", "snippet": "Same content", "link": "https://x.com"}

    with (
        patch("monitor_news.fetch_news", return_value=[item]),
        patch("monitor_news.load_last_seen", return_value=item),
        patch("monitor_news.send_telegram_messages") as mock_telegram,
        patch("monitor_news.save_last_seen") as mock_save,
    ):
        monitor_news.main(preview=True, telegram=True)

    # Should NOT send telegram or save
    mock_telegram.assert_not_called()
    mock_save.assert_not_called()
